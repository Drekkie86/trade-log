"""Re-score one frozen candidate against live ThetaData quotes.

The scan that produced a card may be an hour old. Before an order is placed the
same structure is priced again on the live chain, with the same models and
costs, so the operator sees today's credit, expected profit and score rather
than the ones from the scan.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from src.engine.chains import NY, Chain, fetch_live_chain
from src.engine.pipeline import (
    LANE_MAIN, Candidate, ScanResult, main_config, scan_chain, score_structure,
    trading_days_to_expiry, zero_dte_config,
)
from src.engine.structures import Leg, Structure


@dataclass(frozen=True)
class Reprice:
    status: str                 # OK | NO_LIVE_CHAIN | LEG_NOT_QUOTED | MODEL_UNAVAILABLE
    candidate: Candidate | None = None
    detail: str = ""


def _structure_from_record(record: dict, chain: Chain) -> tuple[Structure | None, str]:
    expiry = next((e for e in chain.expiries if e.expiration == record["expiration"]), None)
    if expiry is None or expiry.forward is None:
        return None, "the live chain has no usable quotes for this expiry"
    legs = []
    for leg in record["legs"]:
        q = next((q for q in expiry.quotes
                  if q.right == leg["right"] and float(q.strike) == float(leg["strike"])), None)
        if q is None or not q.two_sided:
            return None, f"{leg['strike']:g}{leg['right']} has no two-sided live quote"
        legs.append(Leg(q, int(leg["side"])))
    return Structure(record["family"], record["shape"], chain.underlying, record["expiration"],
                     tuple(legs)), ""


def reprice(record: dict, *, theta_client, conn, now: datetime | None = None,
            calendar=None) -> Reprice:
    now = (now or datetime.now(UTC)).astimezone(UTC)
    today = now.astimezone(NY).date()
    lane = record.get("lane", LANE_MAIN)
    config = main_config() if lane == LANE_MAIN else zero_dte_config()
    symbol = record["underlying"]
    chain = fetch_live_chain(theta_client, symbol, asof=now, min_dte=config.min_dte,
                             max_dte=config.max_dte)
    structure, problem = _structure_from_record(record, chain)
    if structure is None:
        return Reprice("NO_LIVE_CHAIN" if "expiry" in problem else "LEG_NOT_QUOTED", detail=problem)

    from src.engine.history import load_closes

    intraday = None
    closes = None
    if lane == LANE_MAIN:
        closes = load_closes(conn, symbol, before=today)
    else:
        from src.engine.intraday import load_intraday_history

        intraday = load_intraday_history(conn, symbol, before=today)
    # Run the regular chain scan so events, history and the gates are identical
    # to the daemon's, then pick out this structure; if the grid did not
    # generate it, score it directly on the same distributions.
    result = ScanResult(lane=lane, asof=now, config=config)
    scored = scan_chain(chain, closes, config, now, result, calendar, intraday=intraday)
    for cand in scored:
        if cand.structure_key == structure.key:
            return Reprice("OK", cand)
    expiry = next(e for e in chain.expiries if e.expiration == record["expiration"])
    dists = _distributions_for(chain, expiry, closes, intraday, config, now, today, calendar)
    if dists is None:
        return Reprice("MODEL_UNAVAILABLE", detail="no model could be built from live data")
    td = trading_days_to_expiry(now, expiry.expiration, calendar)
    cand = score_structure(structure, expiry=expiry, dists=dists[0], config=config, chain=chain,
                           trading_days=td, event_variance=dists[1], asof=now,
                           forecast_vol=dists[2])
    return Reprice("OK", cand)


def _distributions_for(chain, expiry, closes, intraday, config, now, today, calendar):
    from src.engine.models import (
        ModelUnavailable, daily_log_returns, forecast_volatility, implied_event_variance,
    )
    from src.engine.pipeline import _expiry_distributions, _zero_dte_expiry_distributions

    if config.lane != LANE_MAIN:
        dists = _zero_dte_expiry_distributions(expiry, intraday, now, today)
        return (dists, 0.0, None) if dists else None
    usable = [e for e in chain.expiries if e.forward is not None and e.calendar_years > 0 and e.atm_iv]
    events = dict(zip([e.expiration for e in usable],
                      implied_event_variance([(e.calendar_years, e.atm_iv) for e in usable])))
    forecast = None
    if closes:
        try:
            forecast = forecast_volatility(daily_log_returns(closes))
        except ModelUnavailable:
            forecast = None
    td = trading_days_to_expiry(now, expiry.expiration, calendar)
    ev = events.get(expiry.expiration, 0.0)
    dists = _expiry_distributions(expiry, closes, forecast, td, ev)
    if not dists:
        return None
    return dists, ev, (None if forecast is None else forecast.annualized_vol)
