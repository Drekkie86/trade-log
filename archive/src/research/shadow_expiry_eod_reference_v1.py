"""Candidate-linked *reference-only* ThetaData stock EOD payoff study.

This is deliberately offline/read-only. Never execute in a Streamlit page render:
requests are bounded but vendor latency is not a UI dependency. The EOD
report, generally generated after 17:15 ET, can reflect after-hours trades.
It does not establish the underlying at option expiration, OCC settlement,
broker fills or validated trading returns.
"""
from __future__ import annotations

import json
import math
from datetime import date, datetime
from typing import Any, Callable
from zoneinfo import ZoneInfo

from src.database.repository import get_connection
from src.providers.thetadata import ThetaDataError
from src.research.historical_replay_recovery_v1 import (
    HistoricalReplayError, theoretical_expiry_value_usd_minor,
)
from src.research.shadow_outcome_collector_v2 import (
    ShadowOutcomeCollectorError, _entry_cashflow_usd_minor,
)
from src.research.stock_eod_reference_v1 import (
    MEASUREMENT_ROLE, StockEodReference, StockEodReferenceError,
    fetch_stock_eod_reference,
)

NY = ZoneInfo("America/New_York")
DEFAULT_MAX_UNIQUE_REQUESTS = 160
MAX_CANDIDATES = 5000
Fetch = Callable[[str, date], StockEodReference]


def load_expiry_eod_reference_report(
    *, db_path=None, as_of_day: str | None = None,
    fetcher: Fetch = fetch_stock_eod_reference,
    max_unique_requests: int = DEFAULT_MAX_UNIQUE_REQUESTS,
) -> dict[str, Any]:
    """Read frozen proposals and fetch distinct symbol/expiry EOD references.

    Historical snapshots and outcome tables are never updated. A provider
    failure becomes an unresolved source, not a guessed or model-derived price.
    Exceeding the bound fails the *whole* study, not a silent partial sample.
    """
    today = as_of_day or datetime.now(NY).date().isoformat()
    date.fromisoformat(today)
    if not (1 <= max_unique_requests <= 500):
        raise ValueError("INVALID_BOUNDED_EOD_REQUEST_LIMIT")

    conn = get_connection(db_path)
    try:
        conn.execute("PRAGMA query_only = ON")
        rows = [dict(x) for x in conn.execute(
            """SELECT sc.id AS candidate_id,sc.underlying,sc.structure_json,
                      lrc.expiration,sad.proposal_id,sad.estimated_cost_usd_minor,
                      ssp.entry_pricing_json,fx.rate AS entry_eur_to_usd
               FROM shadow_candidates sc
               JOIN listing_reference_contracts lrc
                 ON lrc.id = sc.reference_contract_id
               JOIN v_shadow_admission_decisions_all sad
                 ON sad.candidate_id = sc.id AND sad.decision = 'ADMITTED'
               JOIN shadow_structure_proposals ssp ON ssp.id = sad.proposal_id
               JOIN fx_observations fx ON fx.id = sad.fx_observation_id
               WHERE lrc.expiration < ?
               ORDER BY sc.id""", (today,),
        ).fetchall()]
    finally:
        conn.close()
    if len(rows) > MAX_CANDIDATES:
        raise RuntimeError("EOD_REFERENCE_CANDIDATE_POPULATION_EXCEEDS_LIMIT")
    keys = sorted({(str(x["underlying"]), str(x["expiration"])) for x in rows})
    if len(keys) > max_unique_requests:
        raise RuntimeError("EOD_REFERENCE_REQUEST_POPULATION_EXCEEDS_BOUND")

    pool: dict[tuple[str, str], StockEodReference | None] = {}
    failures: dict[tuple[str, str], str] = {}
    for key in keys:
        try:
            reference = fetcher(key[0], date.fromisoformat(key[1]))
            if (
                not isinstance(reference, StockEodReference)
                or reference.symbol != key[0].upper()
                or reference.session_date != key[1]
                or reference.measurement_role != MEASUREMENT_ROLE
            ):
                raise StockEodReferenceError("EOD_REFERENCE_IDENTITY_MISMATCH")
            pool[key] = reference
        except (ThetaDataError, StockEodReferenceError, TimeoutError, OSError) as exc:
            pool[key] = None
            failures[key] = (
                "SOURCE_UNAVAILABLE" if not isinstance(exc, StockEodReferenceError)
                else "INVALID_SOURCE_REPORT"
            )

    results: list[dict[str, Any]] = []
    for row in rows:
        key = (str(row["underlying"]), str(row["expiration"]))
        ref = pool[key]
        item: dict[str, Any] = {
            "candidate_id": int(row["candidate_id"]),
            "proposal_id": int(row["proposal_id"]),
            "underlying": key[0],
            "expiration": key[1],
            "measurement_role": MEASUREMENT_ROLE,
            "verified_trading_outcome": False,
            "outcome_state": "UNRESOLVED",
            "reason_code": failures.get(key, "NO_EOD_REFERENCE"),
        }
        if ref is None:
            results.append(item)
            continue
        item.update({
            "source": ref.source,
            "source_report_generated_at": ref.report_generated_at,
            "source_last_trade_at": ref.last_trade_at,
            "source_fetched_at": ref.fetched_at,
            "source_row_sha256": ref.row_sha256,
            "source_last_trade_after_1600_ny": ref.last_trade_after_1600_ny,
            "source_reported_eod_close": ref.reported_close,
        })
        try:
            structure = json.loads(str(row["structure_json"]))
            pricing = json.loads(str(row["entry_pricing_json"]))
            entry = _entry_cashflow_usd_minor(
                structure=structure, entry_pricing=pricing
            )
            terminal = theoretical_expiry_value_usd_minor(
                structure=structure, underlying_price=ref.reported_close
            )
            cost = int(row["estimated_cost_usd_minor"])
            fx = float(row["entry_eur_to_usd"])
            if cost < 0 or not math.isfinite(fx) or fx <= 0:
                raise ValueError("INVALID_ORIGINAL_COST_OR_FX")
            net = int(entry) + int(terminal) - cost
            item.update({
                "outcome_state": "EOD_REFERENCE_MODEL_NOT_VALIDATED",
                "reason_code": "AFTER_HOURS_EOD_REFERENCE_NOT_EXPIRY_PRICE"
                if ref.last_trade_after_1600_ny
                else "EOD_REFERENCE_NOT_SETTLEMENT",
                "entry_cashflow_usd_minor": int(entry),
                "terminal_intrinsic_at_eod_usd_minor": int(terminal),
                "assumed_round_trip_cost_usd_minor": cost,
                "indicative_net_usd_minor": net,
                "indicative_net_eur_minor": int(round(net / fx)),
            })
        except (
            ValueError, TypeError, KeyError, ArithmeticError,
            ShadowOutcomeCollectorError, HistoricalReplayError,
        ) as exc:
            item["reason_code"] = "CANNOT_RECONSTRUCT_ORIGINAL_ENTRY_OR_FX"
            item["evidence_error_type"] = type(exc).__name__
        results.append(item)

    estimated = [
        r for r in results
        if r["outcome_state"] == "EOD_REFERENCE_MODEL_NOT_VALIDATED"
    ]
    return {
        "measurement_role": MEASUREMENT_ROLE,
        "total_expired_admitted": len(results),
        "unique_symbol_expiry_requests": len(keys),
        "reference_estimate_count": len(estimated),
        "unresolved_count": len(results) - len(estimated),
        "independent_expiry_dates": len({r["expiration"] for r in estimated}),
        "indicative_positive_count": sum(r["indicative_net_usd_minor"] > 0 for r in estimated),
        "indicative_negative_count": sum(r["indicative_net_usd_minor"] < 0 for r in estimated),
        "rows": results,
        "disclaimer": (
            "ThetaData stock EOD reports are generated after the regular session "
            "and may reflect extended-hours trades; they are not the option-expiry "
            "underlying price, official option settlement, broker fills, or "
            "validated trading returns. Costs and exercise are modeled."
        ),
    }
