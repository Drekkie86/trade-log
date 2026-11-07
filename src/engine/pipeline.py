"""The single trade-finding pipeline.

For every chain: build the distributions per expiry, generate every defined-risk
structure, price each one after costs under every model, and keep a structure
only when it still pays under a mixture of the forecast view and the market's
own (implied) view. Survivors are ranked by expected profit per dollar of
tail risk (expected loss in the worst 5 %).

Gates fail closed: an unknown quote age, a missing model or an undetectable
earnings date rejects the structure instead of letting it through.
"""
from __future__ import annotations

import math
import os
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Mapping, Sequence

import numpy as np

from src.engine import ENGINE_VERSION
from src.engine.chains import NY, Chain, Expiry, parse_utc
from src.engine.models import (
    EMPIRICAL, IMPLIED, VOL_FORECAST, Distribution, ModelUnavailable, VolForecast,
    daily_log_returns, empirical_distribution, forecast_volatility,
    implied_distribution, implied_event_variance, smile_implied_distribution,
    vol_forecast_distribution,
)
from src.engine.structures import (
    FAMILY_LABELS, MULTIPLIER, CostPolicy, GenerationGrid, Structure,
    iter_structures, liquid, pnl,
)

LANE_MAIN = "MAIN"
LANE_ZERO_DTE = "ZERO_DTE"

# Index and sector ETFs: no earnings, so no event detection needed.
NO_EARNINGS_SYMBOLS = {
    "SPY", "QQQ", "IWM", "DIA", "XLF", "XLK", "XLE", "XLV", "XLI", "XLP", "XLY", "SMH",
    "TLT", "GLD", "SLV", "HYG", "XSP", "SPX", "NDX", "RUT", "VIX",
}
MIN_EXPIRIES_FOR_EVENT_DETECTION = 3
TAIL_RISK_FLOOR = 0.10      # risk is never taken below 10 % of max loss


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def event_blackout_from_env(raw: str | None = None) -> dict[str, date]:
    """``CHRISTIANIA_EVENT_BLACKOUT=NVDA:2026-11-19,AAPL:2027-01-28``."""
    raw = os.environ.get("CHRISTIANIA_EVENT_BLACKOUT", "") if raw is None else raw
    out: dict[str, date] = {}
    for item in raw.split(","):
        if ":" not in item:
            continue
        sym, day = item.split(":", 1)
        try:
            out[sym.strip().upper()] = date.fromisoformat(day.strip())
        except ValueError:
            continue
    return out


def no_earnings_symbols() -> set[str]:
    extra = os.environ.get("CHRISTIANIA_NO_EARNINGS_SYMBOLS", "")
    return NO_EARNINGS_SYMBOLS | {s.strip().upper() for s in extra.split(",") if s.strip()}


@dataclass(frozen=True)
class EngineConfig:
    lane: str
    min_dte: int
    max_dte: int
    grid: GenerationGrid
    cost: CostPolicy
    max_quote_age: timedelta
    forecast_weight: float = 0.5          # weight of the forecast view in the score
    stress_jump: float = -0.10            # stress scenario: one shock of this size...
    stress_jump_prob: float = 0.03        # ...with this probability before expiry
    max_relative_spread: float = 0.50
    min_bid: float = 0.05
    min_open_interest: int = 0            # the quote feed carries no open interest
    min_ev_usd: float = 5.0
    min_score: float = 0.03               # mixture EV / tail risk
    top_n: int = 5
    near_misses: int = 5
    decision_time: time = time(10, 0)     # New York; first scan at/after this freezes the picks

    def as_dict(self) -> dict:
        d = asdict(self)
        d["max_quote_age"] = self.max_quote_age.total_seconds()
        d["decision_time"] = self.decision_time.strftime("%H:%M")
        return d


def _cost() -> CostPolicy:
    return CostPolicy(
        slippage_fraction=_env_float("CHRISTIANIA_SLIPPAGE_FRACTION", 0.5),
        # Saxo Classic tier for US stock options; set your own tier in the environment.
        commission_per_contract=_env_float("CHRISTIANIA_COMMISSION_PER_CONTRACT", 2.00),
    )


def main_config() -> EngineConfig:
    return EngineConfig(
        lane=LANE_MAIN, min_dte=7, max_dte=45, grid=GenerationGrid(), cost=_cost(),
        max_quote_age=timedelta(minutes=90),
        forecast_weight=_env_float("CHRISTIANIA_FORECAST_WEIGHT", 0.5),
    )


def zero_dte_config() -> EngineConfig:
    return EngineConfig(
        lane=LANE_ZERO_DTE, min_dte=0, max_dte=1,
        grid=GenerationGrid(short_deltas=(0.05, 0.10, 0.16, 0.20, 0.25),
                            width_steps=(1, 2, 3, 5), fly_wing_steps=(2, 4, 6)),
        cost=_cost(), max_quote_age=timedelta(minutes=5),
        forecast_weight=_env_float("CHRISTIANIA_FORECAST_WEIGHT", 0.5),
        stress_jump=-0.03, stress_jump_prob=0.02,
        min_ev_usd=2.0, top_n=3,
    )


# ------------------------------------------------------------------- horizon
def trading_days_to_expiry(asof: datetime, expiration: str, calendar=None) -> float:
    """Remaining fraction of today's session plus full sessions until expiry."""
    from src.operations.market_calendar import get_xnys_calendar

    cal = calendar or get_xnys_calendar()
    today = asof.astimezone(NY).date()
    expiry = date.fromisoformat(expiration)
    if expiry < today:
        return 0.0
    days = 0.0
    if cal.is_session(today.isoformat()):
        open_at = cal.session_open(today.isoformat()).to_pydatetime()
        close_at = cal.session_close(today.isoformat()).to_pydatetime()
        total = (close_at - open_at).total_seconds()
        left = (close_at - asof.astimezone(UTC)).total_seconds()
        days += min(1.0, max(0.0, left / total))
    if expiry > today:
        sessions = cal.sessions_in_range(
            (today + timedelta(days=1)).isoformat(), expiry.isoformat()
        )
        days += float(len(sessions))
    return days


# ------------------------------------------------------------------- results
@dataclass(frozen=True)
class ModelScore:
    model_id: str
    ev_usd: float
    pop: float
    note: str = ""


@dataclass(frozen=True)
class Candidate:
    lane: str
    underlying: str
    expiration: str
    family: str
    shape: str
    structure_key: str
    description: str
    legs: tuple[dict, ...]
    entry_cash_usd: float
    commission_usd: float
    max_loss_usd: float
    max_gain_usd: float
    breakevens: tuple[float, ...]
    scores: Mapping[str, ModelScore]
    forecast_model: str | None          # the forecast model with the lower EV
    forecast_ev_usd: float              # EV under that model
    implied_ev_usd: float               # EV under the market's own distribution
    conservative_ev_usd: float          # mixture EV: the score basis
    stress_ev_usd: float                # forecast EV with the stress shock
    cvar95_usd: float                   # expected loss in the worst 5 % of the mixture
    p_max_loss: float                   # mixture probability of (nearly) the full loss
    pop: float                          # mixture probability of any profit
    score: float                        # mixture EV / tail risk
    ev_per_risk: float                  # mixture EV / max loss
    forecast_weight: float
    models_agree: bool
    passed: bool
    reject_reason: str | None
    spot: float | None
    forward: float
    atm_iv: float | None
    forecast_vol: float | None
    event_move_pct: float | None
    trading_days: float
    quote_age_seconds: float | None
    captured_at: str
    snapshot_id: int | None

    @property
    def family_label(self) -> str:
        return FAMILY_LABELS.get(self.family, self.family)

    @property
    def is_credit(self) -> bool:
        return self.entry_cash_usd > 0

    def to_record(self) -> dict:
        d = asdict(self)
        d["scores"] = {k: asdict(v) for k, v in self.scores.items()}
        d["legs"] = list(self.legs)
        d["breakevens"] = list(self.breakevens)
        return d


@dataclass
class ScanResult:
    lane: str
    asof: datetime
    config: EngineConfig
    chains_scanned: int = 0
    chains_without_history: list[str] = field(default_factory=list)
    chains_blocked: dict[str, str] = field(default_factory=dict)
    structures_scored: int = 0
    rejections: Counter = field(default_factory=Counter)
    passed: list[Candidate] = field(default_factory=list)
    near_misses: list[Candidate] = field(default_factory=list)
    engine_version: str = ENGINE_VERSION

    @property
    def picks(self) -> list[Candidate]:
        """Best structure per underlying, at most top_n."""
        seen: set[str] = set()
        out = []
        for c in self.passed:
            if c.underlying not in seen:
                seen.add(c.underlying)
                out.append(c)
            if len(out) >= self.config.top_n:
                break
        return out


# ------------------------------------------------------------------- scoring
def _breakevens(structure: Structure, cost: CostPolicy) -> tuple[float, ...]:
    xs = structure.breakpoints()
    ys = pnl(structure, xs, cost)
    out = []
    for (x0, y0), (x1, y1) in zip(zip(xs, ys), zip(xs[1:], ys[1:])):
        if y0 == 0:
            out.append(float(x0))
        elif y0 * y1 < 0:
            out.append(float(x0 + (x1 - x0) * (-y0) / (y1 - y0)))
    return tuple(round(b, 2) for b in out)


def _quote_age(structure: Structure, asof: datetime) -> float | None:
    """Age of the oldest leg quote; None when any leg's timestamp is unusable."""
    ages = []
    for leg in structure.legs:
        stamp = parse_utc(leg.quote.quote_at)
        if stamp is None:
            return None
        ages.append((asof - stamp).total_seconds())
    return max(ages) if ages else None


def _weighted_tail(values: np.ndarray, weights: np.ndarray, tail: float = 0.05) -> float:
    """Expected loss (positive number) in the worst ``tail`` share of a weighted sample."""
    order = np.argsort(values)
    v, w = values[order], weights[order]
    cum = np.cumsum(w)
    inside = cum <= tail
    if not inside.any():
        inside[0] = True
    w_in = w[inside].copy()
    # Fill the tail exactly: part of the first excluded point.
    remaining = tail - cum[inside][-1]
    if remaining > 0 and inside.sum() < len(v):
        idx = inside.sum()
        extra_v, extra_w = v[idx], min(remaining, w[idx])
        loss = -(np.dot(v[inside], w_in) + extra_v * extra_w) / (w_in.sum() + extra_w)
    else:
        loss = -np.dot(v[inside], w_in) / w_in.sum()
    return float(loss)


def score_structure(structure: Structure, *, expiry: Expiry, dists: Mapping[str, Distribution],
                    config: EngineConfig, chain: Chain, trading_days: float,
                    event_variance: float, asof: datetime,
                    forecast_vol: float | None = None) -> Candidate:
    cost = config.cost
    xs = structure.breakpoints()
    ys = pnl(structure, xs, cost)
    max_loss = float(max(0.0, -ys.min()))
    max_gain = float(ys.max())
    values: dict[str, np.ndarray] = {}
    scores: dict[str, ModelScore] = {}
    for model_id, dist in dists.items():
        v = pnl(structure, dist.terminal_prices(expiry.forward), cost)
        values[model_id] = v
        scores[model_id] = ModelScore(model_id, float(v.mean()), float((v > 0).mean()), dist.note)

    forecast_models = [m for m in (VOL_FORECAST, EMPIRICAL) if m in values]
    complete = len(forecast_models) == 2 and IMPLIED in values
    nan = float("nan")
    worse = forecast_ev = implied_ev = mix_ev = stress_ev = cvar = p_max = pop = score = None
    agree = False
    if complete:
        worse = min(forecast_models, key=lambda m: scores[m].ev_usd)
        forecast_ev = scores[worse].ev_usd
        implied_ev = scores[IMPLIED].ev_usd
        agree = all(scores[m].ev_usd > 0 for m in forecast_models)
        w = config.forecast_weight
        fv, iv = values[worse], values[IMPLIED]
        sample = np.concatenate([fv, iv])
        weights = np.concatenate([np.full(len(fv), w / len(fv)), np.full(len(iv), (1 - w) / len(iv))])
        mix_ev = w * forecast_ev + (1 - w) * implied_ev
        pop = float(np.dot(weights, sample > 0))
        p_max = float(np.dot(weights, sample <= -0.95 * max_loss)) if max_loss > 0 else 0.0
        cvar = max(_weighted_tail(sample, weights), TAIL_RISK_FLOOR * max_loss)
        shocked = pnl(structure, dists[worse].terminal_prices(expiry.forward) * (1 + config.stress_jump), cost)
        stress_ev = (1 - config.stress_jump_prob) * forecast_ev + config.stress_jump_prob * float(shocked.mean())
        score = mix_ev / cvar if cvar > 0 else float("-inf")
    age = _quote_age(structure, asof)

    reason = None
    if max_loss <= 0:
        reason = "NO_RISK_ARBITRAGE_SUSPECT"
    elif age is None:
        reason = "QUOTE_AGE_UNKNOWN"
    elif age > config.max_quote_age.total_seconds():
        reason = "STALE_QUOTE"
    elif not complete:
        reason = "MODEL_UNAVAILABLE"
    elif not agree:
        reason = "MODELS_DISAGREE"
    elif mix_ev < config.min_ev_usd:
        reason = "EV_TOO_SMALL"
    elif score < config.min_score:
        reason = "RETURN_ON_RISK_TOO_LOW"

    def r(x, n=2):
        return nan if x is None or not math.isfinite(x) else round(x, n)

    entry = structure.entry_cash_per_share(cost.slippage_fraction) * MULTIPLIER
    event_move = math.sqrt(event_variance) * 100 if event_variance > 0 else None
    return Candidate(
        lane=config.lane, underlying=structure.underlying, expiration=structure.expiration,
        family=structure.family, shape=structure.shape, structure_key=structure.key,
        description=structure.describe(),
        legs=tuple(
            {"right": l.right, "strike": l.strike, "side": l.side,
             "bid": l.quote.bid, "ask": l.quote.ask, "fill": round(l.fill(cost.slippage_fraction), 4),
             "iv": l.quote.iv, "delta": l.quote.delta}
            for l in structure.legs
        ),
        entry_cash_usd=round(entry, 2), commission_usd=round(cost.commission(structure), 2),
        max_loss_usd=round(max_loss, 2), max_gain_usd=round(max_gain, 2),
        breakevens=_breakevens(structure, cost), scores=scores,
        forecast_model=worse, forecast_ev_usd=r(forecast_ev), implied_ev_usd=r(implied_ev),
        conservative_ev_usd=r(mix_ev), stress_ev_usd=r(stress_ev), cvar95_usd=r(cvar),
        p_max_loss=r(p_max, 4), pop=r(pop, 4), score=r(score, 4),
        ev_per_risk=r(mix_ev / max_loss if mix_ev is not None and max_loss > 0 else None, 4),
        forecast_weight=config.forecast_weight,
        models_agree=agree, passed=reason is None, reject_reason=reason,
        spot=chain.spot, forward=round(expiry.forward, 4), atm_iv=expiry.atm_iv,
        forecast_vol=None if forecast_vol is None else round(forecast_vol, 4),
        event_move_pct=round(event_move, 2) if event_move else None,
        trading_days=round(trading_days, 3), quote_age_seconds=age,
        captured_at=chain.captured_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        snapshot_id=chain.snapshot_id,
    )


def _smile_points(expiry: Expiry) -> list[tuple[float, float]]:
    """(log-moneyness, IV) of out-of-the-money two-sided quotes, one per strike."""
    out = []
    for q in expiry.quotes:
        if q.iv is None or not q.two_sided or expiry.forward is None:
            continue
        m = math.log(q.strike / expiry.forward)
        if (q.right == "P" and m < 0) or (q.right == "C" and m > 0):
            out.append((m, q.iv))
    return out


def market_distribution(expiry: Expiry) -> Distribution:
    return smile_implied_distribution(_smile_points(expiry), expiry.atm_iv, expiry.calendar_years)


def _expiry_distributions(expiry: Expiry, closes: Sequence[float] | None,
                          forecast: VolForecast | None, trading_days: float,
                          event_variance: float) -> dict[str, Distribution]:
    dists: dict[str, Distribution] = {}
    if expiry.atm_iv is not None:
        try:
            dists[IMPLIED] = market_distribution(expiry)
        except ModelUnavailable:
            pass
    if forecast is not None:
        try:
            dists[VOL_FORECAST] = vol_forecast_distribution(forecast, trading_days, event_variance)
        except ModelUnavailable:
            pass
    if closes:
        try:
            dists[EMPIRICAL] = empirical_distribution(closes, trading_days, event_variance)
        except ModelUnavailable:
            pass
    return dists


def _zero_dte_expiry_distributions(expiry: Expiry, intraday, asof: datetime,
                                   today: date) -> dict[str, Distribution]:
    from src.engine.intraday import zero_dte_distributions

    dists: dict[str, Distribution] = {}
    if expiry.atm_iv is not None:
        try:
            dists[IMPLIED] = market_distribution(expiry)
        except ModelUnavailable:
            pass
    if intraday is not None:
        try:
            dists.update(zero_dte_distributions(intraday, asof=asof, expiration=expiry.expiration,
                                                today=today))
        except ModelUnavailable:
            pass
    return dists


def scan_chain(chain: Chain, closes: Sequence[float] | None, config: EngineConfig,
               asof: datetime, result: ScanResult, calendar=None, *, intraday=None,
               blackout: Mapping[str, date] | None = None) -> list[Candidate]:
    usable = [e for e in chain.expiries if e.forward is not None and e.calendar_years > 0]
    if not usable:
        result.rejections["NO_USABLE_EXPIRY"] += 1
        return []
    today = asof.astimezone(NY).date()
    events: dict[str, float] = {}
    if config.lane == LANE_MAIN:
        with_iv = [e for e in usable if e.atm_iv]
        if chain.underlying not in no_earnings_symbols() and len(with_iv) < MIN_EXPIRIES_FOR_EVENT_DETECTION:
            result.chains_blocked[chain.underlying] = "EVENT_UNDETECTABLE"
            result.rejections["EVENT_UNDETECTABLE"] += 1
            return []
        events = dict(zip([e.expiration for e in with_iv],
                          implied_event_variance([(e.calendar_years, e.atm_iv) for e in with_iv])))
    event_day = (blackout or {}).get(chain.underlying)
    out: list[Candidate] = []
    history_missing = False
    forecast = None
    if config.lane == LANE_MAIN and closes:
        try:
            forecast = forecast_volatility(daily_log_returns(closes))
        except ModelUnavailable:
            forecast = None
    cache: dict[str, tuple[dict, float, float]] = {}
    for expiry, structure in iter_structures(chain.underlying, usable, config.grid):
        if expiry.expiration not in cache:
            td = trading_days_to_expiry(asof, expiry.expiration, calendar)
            ev = events.get(expiry.expiration, 0.0)
            if config.lane == LANE_ZERO_DTE:
                dists = _zero_dte_expiry_distributions(expiry, intraday, asof, today)
            else:
                dists = _expiry_distributions(expiry, closes, forecast, td, ev)
            if VOL_FORECAST not in dists or EMPIRICAL not in dists:
                history_missing = True
            cache[expiry.expiration] = (dists, td, ev)
        dists, td, ev = cache[expiry.expiration]
        if td <= 0:
            result.rejections["EXPIRED"] += 1
            continue
        if event_day is not None and today <= event_day <= date.fromisoformat(expiry.expiration):
            result.rejections["EVENT_BLACKOUT"] += 1
            continue
        reason = liquid(structure, max_relative_spread=config.max_relative_spread,
                        min_bid=config.min_bid, min_open_interest=config.min_open_interest)
        if reason:
            result.rejections[reason] += 1
            continue
        result.structures_scored += 1
        cand = score_structure(structure, expiry=expiry, dists=dists, config=config,
                               chain=chain, trading_days=td, event_variance=ev, asof=asof,
                               forecast_vol=None if forecast is None else forecast.annualized_vol)
        if not cand.passed:
            result.rejections[cand.reject_reason] += 1
        out.append(cand)
    if history_missing:
        result.chains_without_history.append(chain.underlying)
    return out


def _rank_key(c: Candidate) -> tuple:
    return (-c.score, -c.conservative_ev_usd, c.structure_key)


NEAR_MISS_REASONS = {"MODELS_DISAGREE", "EV_TOO_SMALL", "RETURN_ON_RISK_TOO_LOW"}


def run_scan(chains: Sequence[Chain], closes_by_symbol: Mapping[str, Sequence[float]],
             config: EngineConfig, *, asof: datetime, calendar=None,
             intraday_by_symbol: Mapping[str, object] | None = None,
             blackout: Mapping[str, date] | None = None) -> ScanResult:
    result = ScanResult(lane=config.lane, asof=asof, config=config)
    blackout = event_blackout_from_env() if blackout is None else blackout
    passed: list[Candidate] = []
    near: list[Candidate] = []
    for chain in chains:
        result.chains_scanned += 1
        cands = scan_chain(chain, closes_by_symbol.get(chain.underlying), config, asof, result,
                           calendar, intraday=(intraday_by_symbol or {}).get(chain.underlying),
                           blackout=blackout)
        best_by_underlying: dict[str, Candidate] = {}
        for c in cands:
            if c.passed:
                passed.append(c)
            elif c.reject_reason in NEAR_MISS_REASONS and math.isfinite(c.score):
                cur = best_by_underlying.get(c.underlying)
                if cur is None or _rank_key(c) < _rank_key(cur):
                    best_by_underlying[c.underlying] = c
        near.extend(best_by_underlying.values())
    # Diversify: the best structure per underlying first, then the rest.
    passed.sort(key=_rank_key)
    seen: set[str] = set()
    first, rest = [], []
    for c in passed:
        (rest if c.underlying in seen else first).append(c)
        seen.add(c.underlying)
    result.passed = first + rest
    result.near_misses = sorted(near, key=_rank_key)[: config.near_misses]
    return result
