"""The single trade-finding pipeline.

For every chain: build the market's smile-implied distribution per expiry,
shrink it by the underlying's measured variance risk premium (the REAL_WORLD
distribution), generate every defined-risk short-premium structure, price each
one after costs under both distributions, and keep a structure only when it
pays under the real-world view, still pays with a stress shock, and pays enough
per dollar of tail risk (expected loss in the worst 5 %). Survivors are ranked
by that ratio.

Gates fail closed: an unknown quote age, a missing smile, an underlying without
enough implied/realised history, or an open pick on the same name rejects the
structure instead of letting it through.
"""
from __future__ import annotations

import math
import os
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Collection, Mapping, Sequence

import numpy as np

from src.engine import ENGINE_VERSION
from src.engine.chains import NY, Chain, Expiry, parse_utc
from src.engine.models import (
    IMPLIED, REAL_WORLD, Distribution, ModelUnavailable, RiskPremium, implied_event_variance,
    real_world_distribution, smile_implied_distribution,
)
from src.engine.structures import (
    FAMILY_LABELS, MULTIPLIER, CostPolicy, GenerationGrid, Structure, iter_structures, liquid, pnl,
)

LANE_MAIN = "MAIN"
LANE_ZERO_DTE = "ZERO_DTE"

# Index and sector ETFs: no earnings. Used to group exposure.
NO_EARNINGS_SYMBOLS = {
    "SPY", "QQQ", "IWM", "DIA", "XLF", "XLK", "XLE", "XLV", "XLI", "XLP", "XLY", "SMH",
    "TLT", "GLD", "SLV", "HYG", "XSP", "SPX", "NDX", "RUT", "VIX",
}
MIN_EXPIRIES_FOR_EVENT_DETECTION = 3
TAIL_RISK_FLOOR = 0.10      # risk is never taken below 10 % of max loss
TAIL_SHARE = 0.05


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
    stress_jump: float = -0.10            # stress scenario: one shock of this size...
    stress_jump_prob: float = 0.03        # ...with this probability before expiry
    max_relative_spread: float = 0.50
    min_bid: float = 0.05
    max_loss_per_lot_usd: float = 500.0   # CHRISTIANIA_MAX_LOSS_PER_LOT_USD; set from your capital
    min_open_interest: int = 0            # the quote feed carries no open interest
    min_ev_usd: float = 5.0
    min_score: float = 0.03               # real-world EV / tail risk
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
        # Saxo Bronze tier for US stock options; set your own tier in the environment.
        commission_per_contract=_env_float("CHRISTIANIA_COMMISSION_PER_CONTRACT", 2.00),
    )


def _max_loss_per_lot() -> float:
    return _env_float("CHRISTIANIA_MAX_LOSS_PER_LOT_USD", 500.0)


def main_config() -> EngineConfig:
    return EngineConfig(
        lane=LANE_MAIN, min_dte=7, max_dte=45, grid=GenerationGrid(), cost=_cost(),
        max_loss_per_lot_usd=_max_loss_per_lot(),
        max_quote_age=timedelta(minutes=90),
    )


def zero_dte_config() -> EngineConfig:
    return EngineConfig(
        lane=LANE_ZERO_DTE, min_dte=0, max_dte=1,
        grid=GenerationGrid(short_deltas=(0.05, 0.10, 0.16, 0.20, 0.25),
                            width_steps=(1, 2, 3, 5), fly_wing_steps=(2, 4, 6)),
        cost=_cost(), max_quote_age=timedelta(minutes=5),
        max_loss_per_lot_usd=_max_loss_per_lot(),
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
    ev_usd: float                       # EV under the real-world distribution: the score basis
    implied_ev_usd: float               # EV under the market's own smile (about minus costs)
    stress_ev_usd: float                # real-world EV with the stress shock
    cvar95_usd: float                   # expected loss in the worst 5 % (real-world)
    p_max_loss: float                   # real-world probability of (nearly) the full loss
    pop: float                          # real-world probability of any profit
    score: float                        # ev_usd / cvar95_usd
    ev_per_risk: float                  # ev_usd / max loss
    premium_ratio: float | None         # lambda used
    premium_observations: int | None
    premium_implied_vol: float | None   # window mean implied vol
    premium_realised_vol: float | None  # window mean realised vol
    passed: bool
    reject_reason: str | None
    spot: float | None
    forward: float
    atm_iv: float | None
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
    premiums: dict[str, dict] = field(default_factory=dict)
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


def _tail_loss(values: np.ndarray, share: float = TAIL_SHARE) -> float:
    """Expected loss (positive number) in the worst ``share`` of an equally weighted sample."""
    n = max(1, int(round(len(values) * share)))
    worst = np.sort(values)[:n]
    return float(-worst.mean())


def score_structure(structure: Structure, *, expiry: Expiry, market: Distribution | None,
                    premium: RiskPremium | None, config: EngineConfig, chain: Chain,
                    trading_days: float, event_variance: float, asof: datetime) -> Candidate:
    cost = config.cost
    xs = structure.breakpoints()
    ys = pnl(structure, xs, cost)
    max_loss = float(max(0.0, -ys.min()))
    max_gain = float(ys.max())
    entry = structure.entry_cash_per_share(cost.slippage_fraction) * MULTIPLIER
    scores: dict[str, ModelScore] = {}
    nan = float("nan")
    ev = implied_ev = stress_ev = cvar = p_max = pop = score = None
    complete = False
    if market is not None:
        mv = pnl(structure, market.terminal_prices(expiry.forward), cost)
        scores[IMPLIED] = ModelScore(IMPLIED, float(mv.mean()), float((mv > 0).mean()), market.note)
        implied_ev = float(mv.mean())
        if premium is not None:
            try:
                real = real_world_distribution(market, premium)
            except ModelUnavailable:
                real = None
            if real is not None:
                prices = real.terminal_prices(expiry.forward)
                rv = pnl(structure, prices, cost)
                scores[REAL_WORLD] = ModelScore(REAL_WORLD, float(rv.mean()), float((rv > 0).mean()), real.note)
                ev = float(rv.mean())
                pop = float((rv > 0).mean())
                p_max = float((rv <= -0.95 * max_loss).mean()) if max_loss > 0 else 0.0
                cvar = max(_tail_loss(rv), TAIL_RISK_FLOOR * max_loss)
                shocked = pnl(structure, prices * (1 + config.stress_jump), cost)
                stress_ev = (1 - config.stress_jump_prob) * ev + config.stress_jump_prob * float(shocked.mean())
                score = ev / cvar if cvar > 0 else float("-inf")
                complete = True
    age = _quote_age(structure, asof)

    reason = None
    if max_loss <= 0:
        reason = "NO_RISK_ARBITRAGE_SUSPECT"
    elif entry <= 0:
        reason = "NOT_A_CREDIT"
    elif max_loss > config.max_loss_per_lot_usd:
        reason = "MAX_LOSS_TOO_LARGE"
    elif age is None:
        reason = "QUOTE_AGE_UNKNOWN"
    elif age > config.max_quote_age.total_seconds():
        reason = "STALE_QUOTE"
    elif not complete:
        reason = "MODEL_UNAVAILABLE"
    elif ev < config.min_ev_usd:
        reason = "EV_TOO_SMALL"
    elif stress_ev < 0:
        reason = "STRESS_EV_NEGATIVE"
    elif score < config.min_score:
        reason = "RETURN_ON_RISK_TOO_LOW"

    def r(x, n=2):
        return nan if x is None or not math.isfinite(x) else round(x, n)

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
        ev_usd=r(ev), implied_ev_usd=r(implied_ev), stress_ev_usd=r(stress_ev), cvar95_usd=r(cvar),
        p_max_loss=r(p_max, 4), pop=r(pop, 4), score=r(score, 4),
        ev_per_risk=r(ev / max_loss if ev is not None and max_loss > 0 else None, 4),
        premium_ratio=None if premium is None else round(premium.ratio, 4),
        premium_observations=None if premium is None else premium.observations,
        premium_implied_vol=None if premium is None else round(premium.implied_vol, 4),
        premium_realised_vol=None if premium is None else round(premium.realised_vol, 4),
        passed=reason is None, reject_reason=reason,
        spot=chain.spot, forward=round(expiry.forward, 4), atm_iv=expiry.atm_iv,
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


def _market_or_none(expiry: Expiry) -> Distribution | None:
    if expiry.atm_iv is None:
        return None
    try:
        return market_distribution(expiry)
    except ModelUnavailable:
        return None


def event_variances(chain: Chain) -> dict[str, float]:
    """Expiration -> cumulative priced event variance, from the ATM term structure."""
    with_iv = [e for e in chain.expiries if e.forward is not None and e.calendar_years > 0 and e.atm_iv]
    if len(with_iv) < MIN_EXPIRIES_FOR_EVENT_DETECTION:
        return {}
    return dict(zip([e.expiration for e in with_iv],
                    implied_event_variance([(e.calendar_years, e.atm_iv) for e in with_iv])))


def scan_chain(chain: Chain, premium: RiskPremium | None, config: EngineConfig,
               asof: datetime, result: ScanResult, calendar=None, *,
               blackout: Mapping[str, date] | None = None,
               open_position: bool = False) -> list[Candidate]:
    if open_position:
        result.chains_blocked[chain.underlying] = "OPEN_POSITION"
        result.rejections["OPEN_POSITION"] += 1
        return []
    usable = [e for e in chain.expiries if e.forward is not None and e.calendar_years > 0]
    if not usable:
        result.rejections["NO_USABLE_EXPIRY"] += 1
        return []
    today = asof.astimezone(NY).date()
    events = event_variances(chain)
    event_day = (blackout or {}).get(chain.underlying)
    if premium is None:
        result.chains_without_history.append(chain.underlying)
    else:
        result.premiums[chain.underlying] = {
            "ratio": round(premium.ratio, 4), "observations": premium.observations,
            "implied_vol": round(premium.implied_vol, 4), "realised_vol": round(premium.realised_vol, 4),
        }
    out: list[Candidate] = []
    cache: dict[str, tuple[Distribution | None, float, float]] = {}
    for expiry, structure in iter_structures(chain.underlying, usable, config.grid):
        if expiry.expiration not in cache:
            cache[expiry.expiration] = (_market_or_none(expiry),
                                        trading_days_to_expiry(asof, expiry.expiration, calendar),
                                        events.get(expiry.expiration, 0.0))
        market, td, ev = cache[expiry.expiration]
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
        cand = score_structure(structure, expiry=expiry, market=market, premium=premium, config=config,
                               chain=chain, trading_days=td, event_variance=ev, asof=asof)
        if not cand.passed:
            result.rejections[cand.reject_reason] += 1
        out.append(cand)
    return out


def _rank_key(c: Candidate) -> tuple:
    return (-c.score, -c.ev_usd, c.structure_key)


NEAR_MISS_REASONS = {"EV_TOO_SMALL", "STRESS_EV_NEGATIVE", "RETURN_ON_RISK_TOO_LOW"}


def run_scan(chains: Sequence[Chain], premiums: Mapping[str, RiskPremium | None],
             config: EngineConfig, *, asof: datetime, calendar=None,
             blackout: Mapping[str, date] | None = None,
             open_underlyings: Collection[str] = ()) -> ScanResult:
    """Score every chain. ``open_underlyings`` are skipped: one open pick per name
    at a time, so the same view is never stacked day after day."""
    result = ScanResult(lane=config.lane, asof=asof, config=config)
    blackout = event_blackout_from_env() if blackout is None else blackout
    open_names = {s.upper() for s in open_underlyings}
    passed: list[Candidate] = []
    near: list[Candidate] = []
    for chain in chains:
        result.chains_scanned += 1
        cands = scan_chain(chain, premiums.get(chain.underlying), config, asof, result, calendar,
                           blackout=blackout, open_position=chain.underlying.upper() in open_names)
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
