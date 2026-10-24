"""Deterministic bounded source selection for multi-strategy option geometry.

Freeze an expiry/strike search universe *before* the outcome. The underlying
spot is an independently sourced as-of stock reference, not Theta model spot.
Returned rows are actual Theta option quote IDs with Massive listing joins.
"""
from __future__ import annotations

from datetime import date,datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

VERSION = "BOUNDED_EXPIRY_STRIKE_DISCOVERY_V1"
TARGET_DTE = (7,14,21,30,40,45)
MAX_SOURCE_EXPIRIES = 64
MAX_STRIKE_LOOKUP = 12
MAX_SELECTED_STRIKES = 5
NY = ZoneInfo("America/New_York")


def read_bounded_strategy_source_rows(
    conn, *,
    snapshot_id: int,
    research_run_id: int,
    underlying: str,
    captured_at: str,
    spot: Decimal,
):
    """Return <=60 exact source quotes and a stable provenance blocker.

    This precommits maturity and ATM breadth, not historical payoffs.
    No broad research-run scan or inferred strike/multiplier is permitted.
    """
    if Decimal(str(spot)) <= 0:
        return [], "INDEPENDENT_SPOT_NOT_POSITIVE"
    try:
        asof = datetime.fromisoformat(
            str(captured_at).replace("Z","+00:00")
        )
        if asof.tzinfo is None or asof.utcoffset() is None:
            return [], "SOURCE_CUT_NOT_AWARE"
        session = asof.astimezone(NY).date()
        raw_expiries = [
            r[0] for r in conn.execute(
                """SELECT DISTINCT expiration FROM option_quotes
                   WHERE snapshot_id=? ORDER BY expiration LIMIT ?""",
                (snapshot_id,MAX_SOURCE_EXPIRIES+1),
            ).fetchall()
        ]
        if len(raw_expiries)>MAX_SOURCE_EXPIRIES:
            return [], "SOURCE_EXPIRIES_EXCEED_BOUNDED_SEARCH"
        maturities = []
        for raw in raw_expiries:
            expiry=date.fromisoformat(str(raw))
            dte=(expiry-session).days
            if dte>=0:
                maturities.append((expiry.isoformat(),dte))
        if not maturities:
            return [], "NO_CURRENT_LISTED_EXPIRY"
        expiries=sorted({
            min(
                maturities,
                key=lambda e: (
                    abs(e[1]-target),e[1],e[0],
                ),
            )[0] for target in TARGET_DTE
        })
        selected = []
        for expiration in expiries:
            nearest={}
            for right in ("C","P"):
                found=conn.execute(
                    """SELECT strike FROM option_quotes
                       WHERE snapshot_id=? AND expiration=? AND right=?
                       GROUP BY strike
                       ORDER BY ABS(strike-?),strike LIMIT ?""",
                    (snapshot_id,expiration,right,
                     float(spot),MAX_STRIKE_LOOKUP),
                ).fetchall()
                nearest[right]={Decimal(str(r[0])) for r in found}
            common=nearest["C"] & nearest["P"]
            if len(common)<3:
                continue
            middle=min(common,key=lambda k: (abs(k-spot),k))
            below=sorted((k for k in common if k<middle),reverse=True)[:2]
            above=sorted((k for k in common if k>middle))[:2]
            if not below or not above:
                continue
            strikes=sorted(set([middle,*below,*above]))
            assert len(strikes)<=MAX_SELECTED_STRIKES
            placeholders=",".join("?" for _ in strikes)
            found=conn.execute(
                f"""SELECT oq.id,oq.snapshot_id,oq.right,oq.strike,
                           oq.expiration,oq.quote_at,oq.bid,oq.ask,
                           oq.shares_per_contract AS quote_multiplier,
                           lrc.shares_per_contract AS reference_multiplier
                    FROM option_quotes oq
                    LEFT JOIN listing_reference_contracts lrc
                      ON lrc.research_run_id=? AND lrc.provider='MASSIVE'
                     AND lrc.underlying=? AND lrc.expiration=oq.expiration
                     AND lrc.right=oq.right AND lrc.strike=oq.strike
                    WHERE oq.snapshot_id=? AND oq.expiration=?
                      AND oq.strike IN ({placeholders})
                    ORDER BY oq.id LIMIT ?""",
                (research_run_id,underlying,snapshot_id,expiration,
                 *(float(x) for x in strikes),MAX_SELECTED_STRIKES*2+1),
            ).fetchall()
            if len(found)>MAX_SELECTED_STRIKES*2:
                return [], "DUPLICATED_OPTION_LISTINGS_AT_SELECTED_STRIKES"
            selected.extend(found)
        if not selected:
            return [], "NO_COMMON_ATM_STRIKE_GEOMETRY"
        return selected,None
    except (TypeError,ValueError,OverflowError):
        return [], "EXPIRY_OR_STRIKE_SOURCE_INVALID"
