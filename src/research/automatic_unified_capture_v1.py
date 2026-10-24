"""Automatic, bounded cross-strategy prospective capture after Theta persistence.

One source snapshot -> one immutable disposition. When real stock evidence
and option geometry qualify, freeze all seven retail strategies with the
same shared no-forecast evidence gate. This is a prospective *NO TRADE*
ledger, not an automatic profitable-trade finder or a brokerage order.
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from src.database.repository import assert_schema_version, get_connection
from src.decision.unified_prospective_ledger_v1 import freeze_market_decisions
from src.decision.unified_trade_ranker_v1 import OptionCandidate
from src.operations.sqlite_runtime import open_readonly_connection
from src.research.independent_family_discovery_v1 import (
    _stock_reference_valid, discover_independent_families,
)
from src.research.independent_family_read_model_v1 import _read_chain
from src.research.massive_underlying_observation_v1 import (
    verified_stock_source_from_notes,
)
from src.research.strategy_competition_v1 import _fx_asof
from src.research.strategy_falsification_v1 import QuoteCostPolicy, dec

VERSION = "AUTOMATIC_UNIFIED_CAPTURE_V1"
MAX_SNAPSHOT_LAG = timedelta(minutes=15)
MAX_FREEZABLE_STRUCTURES = 200


@dataclass(frozen=True)
class AutoCaptureReceipt:
    snapshot_id: int
    research_run_id: int
    status: str
    reason: str
    structures_compared: int
    decisions_frozen: int
    authority: str = "NONE"


def _clock(raw: str) -> datetime:
    ts = datetime.fromisoformat(str(raw).replace("Z","+00:00"))
    if ts.tzinfo is None or ts.utcoffset() is None:
        raise ValueError("SOURCE_TIMESTAMP_NOT_AWARE")
    return ts.astimezone(UTC)


def _bounded_reason(raw: str) -> str:
    # Reason codes only: do not leak provider payloads, credentials or SQL.
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ_0123456789")
    return "".join(c for c in str(raw).upper() if c in allowed)[:90] or "UNKNOWN"


def _existing(conn, run_id: int, snapshot_id: int) -> AutoCaptureReceipt | None:
    row = conn.execute(
        """SELECT research_run_id,snapshot_id,state,reason_code,
                  structures_compared,decisions_frozen
           FROM unified_capture_dispositions_v1 WHERE snapshot_id=?""",
        (snapshot_id,),
    ).fetchone()
    if row is None:
        return None
    if int(row["research_run_id"]) != run_id:
        raise ValueError("EXISTING_CAPTURE_RUN_IDENTITY_CONFLICT")
    return AutoCaptureReceipt(
        snapshot_id,run_id,str(row["state"]),str(row["reason_code"]),
        int(row["structures_compared"]),int(row["decisions_frozen"]),
    )


def capture_frozen_snapshot(
    *, research_run_id: int, snapshot_id: int, db_path=None,
) -> AutoCaptureReceipt:
    """Best-effort selection processing; the outcome is always persisted.

    Source collection has already committed its snapshot. A failure in the
    *new* scoring branch is retained as CAPTURE_FAILURE without undoing
    independently valuable quote evidence.
    """
    assert_schema_version(db_path)
    conn = get_connection(db_path)
    try:
        previous = _existing(conn,research_run_id,snapshot_id)
        if previous is not None:
            return previous
        conn.execute("SELECT 1").fetchone()
    finally:
        conn.close()

    state, reason, compared, frozen = (
        "CAPTURE_FAILURE","UNINITIALIZED",0,0
    )
    try:
        conn = open_readonly_connection(db_path)
        try:
            row = conn.execute(
                """SELECT id,research_run_id,provider,underlying,captured_at,
                          underlying_price,underlying_source,underlying_at,
                          notes
                   FROM market_snapshots WHERE id=?""",
                (snapshot_id,),
            ).fetchone()
            if row is None or int(row["research_run_id"] or -1) != research_run_id:
                raise ValueError("SNAPSHOT_RUN_IDENTITY_MISMATCH")
            cut = _clock(str(row["captured_at"]))
            now = datetime.now(UTC)
            if not timedelta(0) <= now-cut <= MAX_SNAPSHOT_LAG:
                state, reason = (
                    "OUTSIDE_PROSPECTIVE_WINDOW","SOURCE_TOO_OLD_OR_FUTURE"
                )
            elif row["provider"] != "THETADATA":
                state, reason = "EVIDENCE_REJECTED","NOT_THETA_OPTION_SNAPSHOT"
            else:
                # Check independent spot first. Do not scan thousands of
                # option quotes if the required stock evidence is absent.
                raw_spot = (
                    None if row["underlying_price"] is None
                    else dec(row["underlying_price"])
                )
                from src.research.independent_family_discovery_v1 import FrozenChain
                spot_check = FrozenChain(
                    snapshot_id,str(row["underlying"]),str(row["captured_at"]),
                    raw_spot,
                    (
                        verified_stock_source_from_notes(row["notes"])
                        if row["underlying_source"] == "FETCHED" else None
                    ),
                    row["underlying_at"],(),
                )
                if not _stock_reference_valid(spot_check):
                    state, reason = "NO_SOURCE","INDEPENDENT_STOCK_PRICE_NOT_QUALIFIED"
                else:
                    chain = _read_chain(
                        conn,row,research_run_id=research_run_id,
                        bounded_live_selection=True,
                    )
                    fx,fx_at,fx_source = _fx_asof(conn,chain.captured_at)
                    policy = QuoteCostPolicy(
                        option_cost_per_contract_side_usd=Decimal("3"),
                        stock_round_trip_cost_usd=None,
                        eur_to_usd=None if fx is None else dec(fx),
                        cost_provenance="SAXO_RESEARCH_ESTIMATE_NOT_BROKER",
                        fx_provenance=fx_source,
                        max_quote_age_seconds=15,
                        max_leg_quote_skew_seconds=15,
                        bankroll_eur=Decimal("500"),
                        additional_round_trip_cost_usd=None,
                        tax_cost_usd=None,
                        fx_observed_at=fx_at,
                    )
                    discovered = discover_independent_families(chain,policy)
                    compared = len(discovered.source_structures)
                    if compared > MAX_FREEZABLE_STRUCTURES:
                        state,reason = "EVIDENCE_REJECTED","TOO_MANY_STRATEGIES"
                    elif not compared:
                        state = (
                            "NO_GEOMETRY" if discovered.state ==
                            "NO_SUPPORTED_STRATEGY_GEOMETRY"
                            else "EVIDENCE_REJECTED"
                        )
                        reason = (
                            discovered.blockers[0] if discovered.blockers
                            else discovered.state
                        )
                    else:
                        candidates = tuple(
                            OptionCandidate(
                                snapshot_id=chain.snapshot_id,
                                underlying=chain.underlying,
                                expiration=str(s.legs[0].expiration),
                                structure=s,cost_policy=policy,
                                model_inputs=(),lane="MAIN",
                            )
                            for s in discovered.source_structures
                        )
        finally:
            conn.close()
        if compared and state == "CAPTURE_FAILURE":
            receipt = freeze_market_decisions(
                research_run_id=research_run_id,
                candidates=candidates,db_path=db_path,
                record_capture_disposition=True,
            )
            frozen = len(receipt.candidate_ids)
            state, reason = "FROZEN_NO_TRADE","UNPROVEN_FORECAST_NO_TRADE"
    except (ValueError,TypeError,OverflowError) as exc:
        state, reason = "CAPTURE_FAILURE", _bounded_reason(str(exc))
    except sqlite3.Error as exc:
        state, reason = "CAPTURE_FAILURE", "SQLITE_EVIDENCE_READ_ERROR"

    assert state != "CAPTURE_FAILURE" or reason != "UNINITIALIZED"
    with closing(get_connection(db_path)) as conn:
        existing = _existing(conn,research_run_id,snapshot_id)
        if existing is not None:
            return existing
        with conn:
            conn.execute(
            """INSERT INTO unified_capture_dispositions_v1
              (research_run_id,snapshot_id,captured_at,evaluated_at,
               state,reason_code,structures_compared,decisions_frozen)
              SELECT ?,?,captured_at,?,?,?,?,?
              FROM market_snapshots WHERE id=?
              ON CONFLICT(snapshot_id) DO NOTHING""",
            (research_run_id,snapshot_id,
             datetime.now(UTC).isoformat().replace("+00:00","Z"),
             state,_bounded_reason(reason),compared,frozen,snapshot_id),
        )
        prior = _existing(conn,research_run_id,snapshot_id)
        if prior is None:
            raise RuntimeError("UNIFIED_CAPTURE_DISPOSITION_NOT_PERSISTED")
        return prior
