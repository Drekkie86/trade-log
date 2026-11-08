"""Re-score one frozen candidate against live ThetaData quotes.

The scan that produced a card may be an hour old. Before an order is placed the
same structure is priced again on the live chain, with the same distributions,
risk premium and costs, so the operator sees today's credit, expected profit
and score rather than the ones from the scan.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from src.engine.chains import NY, Chain, fetch_live_chain
from src.engine.pipeline import (
    LANE_MAIN, Candidate, ScanResult, _market_or_none, event_variances, main_config, scan_chain,
    score_structure, trading_days_to_expiry, zero_dte_config,
)
from src.engine.premium import risk_premium_for
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

    premium = risk_premium_for(conn, symbol, before=today)
    # Run the regular chain scan so the gates are identical to the daemon's, then
    # pick out this structure; if the grid did not generate it, score it directly
    # on the same distributions.
    result = ScanResult(lane=lane, asof=now, config=config)
    scored = scan_chain(chain, premium, config, now, result, calendar)
    for cand in scored:
        if cand.structure_key == structure.key:
            return Reprice("OK", cand)
    expiry = next(e for e in chain.expiries if e.expiration == record["expiration"])
    market = _market_or_none(expiry)
    if market is None or premium is None:
        return Reprice("MODEL_UNAVAILABLE",
                       detail="no smile on the live chain" if market is None
                       else "not enough implied/realised history for this name")
    td = trading_days_to_expiry(now, expiry.expiration, calendar)
    cand = score_structure(structure, expiry=expiry, market=market, premium=premium, config=config,
                           chain=chain, trading_days=td,
                           event_variance=event_variances(chain).get(expiry.expiration, 0.0), asof=now)
    return Reprice("OK", cand)
