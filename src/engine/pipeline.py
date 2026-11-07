"""The single trade-finding pipeline.

For every chain: build the three distributions per expiry, generate every
defined-risk structure, price each one after costs under every model, and
keep a structure only when even the more pessimistic forecast model says it
pays. Survivors are ranked by conservative EV per dollar at risk.
"""
from __future__ import annotations

import math
import os
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Mapping, Sequence

import numpy as np

from src.engine import ENGINE_VERSION
from src.engine.chains import NY, Chain, Expiry, parse_utc
from src.engine.models import (
    EMPIRICAL, IMPLIED, VOL_FORECAST, Distribution, ModelUnavailable, VolForecast,
    daily_log_returns, empirical_distribution, forecast_volatility,
    implied_distribution, implied_event_variance, vol_forecast_distribution,
)
from src.engine.structures import (
    FAMILY_LABELS, MULTIPLIER, CostPolicy, GenerationGrid, Structure,
    iter_structures, liquid, pnl,
)

LANE_MAIN = "MAIN"
LANE_ZERO_DTE = "ZERO_DTE"


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class EngineConfig:
    lane: str
    min_dte: int
    max_dte: int
    grid: GenerationGrid
    cost: CostPolicy
    max_quote_age: timedelta
    max_relative_spread: float = 0.20
    max_abs_spread: float = 0.05
    min_open_interest: int = 50
    min_ev_usd: float = 5.0
    min_ev_per_risk: float = 0.03
    top_n: int = 5
    near_misses: int = 5

    def as_dict(self) -> dict:
        d = asdict(self)
        d["max_quote_age"] = self.max_quote_age.total_seconds()
        return d


def main_config() -> EngineConfig:
    return EngineConfig(
        lane=LANE_MAIN, min_dte=7, max_dte=45, grid=GenerationGrid(),
        cost=CostPolicy(
            slippage_fraction=_env_float("CHRISTIANIA_SLIPPAGE_FRACTION", 0.5),
            commission_per_contract=_env_float("CHRISTIANIA_COMMISSION_PER_CONTRACT", 0.65),
        ),
        max_quote_age=timedelta(minutes=90),
    )


def zero_dte_config() -> EngineConfig:
    return EngineConfig(
        lane=LANE_ZERO_DTE, min_dte=0, max_dte=1,
        grid=GenerationGrid(short_deltas=(0.05, 0.10, 0.16, 0.20, 0.25),
                            width_steps=(1, 2, 3, 5), fly_wing_steps=(2, 4, 6)),
        cost=CostPolicy(
            slippage_fraction=_env_float("CHRISTIANIA_SLIPPAGE_FRACTION", 0.5),
            commission_per_contract=_env_float("CHRISTIANIA_COMMISSION_PER_CONTRACT", 0.65),
        ),
        max_quote_age=timedelta(minutes=5),
        min_open_interest=0, min_ev_usd=2.0, min_ev_per_risk=0.03, top_n=3,
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
    conservative_ev_usd: float
    ev_per_risk: float
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
    structures_scored: int = 0
    rejections: Counter = field(default_factory=Counter)
    passed: list[Candidate] = field(default_factory=list)
    near_misses: list[Candidate] = field(default_factory=list)
    engine_version: str = ENGINE_VERSION

    @property
    def picks(self) -> list[Candidate]:
        return self.passed[: self.config.top_n]


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
    ages = []
    for leg in structure.legs:
        stamp = parse_utc(leg.quote.quote_at)
        if stamp is None:
            return None
        ages.append((asof - stamp).total_seconds())
    return max(ages) if ages else None


def score_structure(structure: Structure, *, expiry: Expiry, dists: Mapping[str, Distribution],
                    config: EngineConfig, chain: Chain, trading_days: float,
                    event_variance: float, asof: datetime,
                    forecast_vol: float | None = None) -> Candidate:
    cost = config.cost
    xs = structure.breakpoints()
    ys = pnl(structure, xs, cost)
    max_loss = float(max(0.0, -ys.min()))
    max_gain = float(ys.max())
    scores: dict[str, ModelScore] = {}
    for model_id, dist in dists.items():
        values = pnl(structure, dist.terminal_prices(expiry.forward), cost)
        scores[model_id] = ModelScore(model_id, float(values.mean()),
                                      float((values > 0).mean()), dist.note)
    forecast = [scores[m].ev_usd for m in (VOL_FORECAST, EMPIRICAL) if m in scores]
    conservative = min(forecast) if len(forecast) == 2 else float("-inf")
    agree = len(forecast) == 2 and all(v > 0 for v in forecast)
    ev_per_risk = conservative / max_loss if max_loss > 0 else float("-inf")
    age = _quote_age(structure, asof)

    reason = None
    if max_loss <= 0:
        reason = "NO_RISK_ARBITRAGE_SUSPECT"
    elif age is not None and age > config.max_quote_age.total_seconds():
        reason = "STALE_QUOTE"
    elif len(forecast) < 2:
        reason = "MODEL_UNAVAILABLE"
    elif not agree:
        reason = "MODELS_DISAGREE"
    elif conservative < config.min_ev_usd:
        reason = "EV_TOO_SMALL"
    elif ev_per_risk < config.min_ev_per_risk:
        reason = "RETURN_ON_RISK_TOO_LOW"

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
        conservative_ev_usd=round(conservative, 2) if math.isfinite(conservative) else conservative,
        ev_per_risk=round(ev_per_risk, 4) if math.isfinite(ev_per_risk) else ev_per_risk,
        models_agree=agree, passed=reason is None, reject_reason=reason,
        spot=chain.spot, forward=round(expiry.forward, 4), atm_iv=expiry.atm_iv,
        forecast_vol=None if forecast_vol is None else round(forecast_vol, 4),
        event_move_pct=round(event_move, 2) if event_move else None,
        trading_days=round(trading_days, 3), quote_age_seconds=age,
        captured_at=chain.captured_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        snapshot_id=chain.snapshot_id,
    )


def _expiry_distributions(expiry: Expiry, closes: Sequence[float] | None,
                          forecast: VolForecast | None, trading_days: float,
                          event_variance: float) -> tuple[dict[str, Distribution], list[str]]:
    dists: dict[str, Distribution] = {}
    problems: list[str] = []
    if expiry.atm_iv is not None:
        try:
            dists[IMPLIED] = implied_distribution(expiry.atm_iv, expiry.calendar_years)
        except ModelUnavailable as exc:
            problems.append(str(exc))
    if forecast is not None:
        try:
            dists[VOL_FORECAST] = vol_forecast_distribution(forecast, trading_days, event_variance)
        except ModelUnavailable as exc:
            problems.append(str(exc))
    if closes:
        try:
            dists[EMPIRICAL] = empirical_distribution(closes, trading_days, event_variance)
        except ModelUnavailable as exc:
            problems.append(str(exc))
    else:
        problems.append("no daily close history")
    return dists, problems


def scan_chain(chain: Chain, closes: Sequence[float] | None, config: EngineConfig,
               asof: datetime, result: ScanResult, calendar=None) -> list[Candidate]:
    usable = [e for e in chain.expiries if e.forward is not None and e.calendar_years > 0]
    if not usable:
        result.rejections["NO_USABLE_EXPIRY"] += 1
        return []
    # Event detection only on the multi-expiry main lane.
    if config.lane == LANE_MAIN:
        term = [(e.calendar_years, e.atm_iv) for e in usable if e.atm_iv]
        events = dict(zip([e.expiration for e in usable if e.atm_iv],
                          implied_event_variance(term)))
    else:
        events = {}
    out: list[Candidate] = []
    history_missing = False
    forecast = None
    if closes:
        try:
            forecast = forecast_volatility(daily_log_returns(closes))
        except ModelUnavailable:
            forecast = None
    cache: dict[str, tuple[dict, float, float]] = {}
    for expiry, structure in iter_structures(chain.underlying, usable, config.grid):
        if expiry.expiration not in cache:
            td = trading_days_to_expiry(asof, expiry.expiration, calendar)
            ev = events.get(expiry.expiration, 0.0)
            dists, problems = _expiry_distributions(expiry, closes, forecast, td, ev)
            if VOL_FORECAST not in dists or EMPIRICAL not in dists:
                history_missing = True
            cache[expiry.expiration] = (dists, td, ev)
        dists, td, ev = cache[expiry.expiration]
        if td <= 0:
            result.rejections["EXPIRED"] += 1
            continue
        reason = liquid(structure, max_relative_spread=config.max_relative_spread,
                        max_abs_spread=config.max_abs_spread,
                        min_open_interest=config.min_open_interest)
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
    return (-c.ev_per_risk, -c.conservative_ev_usd, c.structure_key)


def run_scan(chains: Sequence[Chain], closes_by_symbol: Mapping[str, Sequence[float]],
             config: EngineConfig, *, asof: datetime, calendar=None) -> ScanResult:
    result = ScanResult(lane=config.lane, asof=asof, config=config)
    passed: list[Candidate] = []
    near: list[Candidate] = []
    for chain in chains:
        result.chains_scanned += 1
        cands = scan_chain(chain, closes_by_symbol.get(chain.underlying), config, asof,
                           result, calendar)
        best_by_underlying: dict[str, Candidate] = {}
        for c in cands:
            if c.passed:
                passed.append(c)
            elif c.reject_reason in {"MODELS_DISAGREE", "EV_TOO_SMALL", "RETURN_ON_RISK_TOO_LOW"} \
                    and math.isfinite(c.ev_per_risk):
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
