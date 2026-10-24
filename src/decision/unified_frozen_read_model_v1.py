"""One read-only, tamper-evident operator source for frozen strategy decisions.

Do not reconstruct "recommendations" from legacy butterfly scores. Rows are
read from the same immutable input/evaluation ledger used for all strategies.
Stale rows and unproven models NEVER surface as actionable manual re-quotes.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from src.decision.unified_trade_ranker_v1 import (
    MarketDecision, RankedOpportunity, MANUAL_REQUOTE, NO_TRADE,
)
from src.operations.sqlite_runtime import open_readonly_connection

MAX_LEDGER_ROWS = 200
SOURCE_MAX_AGE = timedelta(minutes=15)


@dataclass(frozen=True)
class FrozenBookReport:
    decision: MarketDecision | None
    latest_snapshot_at: str | None
    last_run_id: int | None
    records: int
    authority: str = "NONE"


def _time(raw: str) -> datetime:
    ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    if ts.tzinfo is None or ts.utcoffset() is None:
        raise ValueError("FROZEN_LEDGER_TIMESTAMP_NOT_AWARE")
    return ts.astimezone(UTC)


def load_latest_frozen_book(
    *, db_path=None, now: datetime | None = None,
) -> FrozenBookReport:
    """No writes, no historical full scan; fail closed on missing proof."""
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError("CURRENT_TIME_NOT_AWARE")
    now = now.astimezone(UTC)
    conn = open_readonly_connection(db_path)
    try:
        record = conn.execute(
            "SELECT research_run_id FROM unified_candidate_decisions_v1 "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if record is None:
            return FrozenBookReport(None, None, None, 0)
        run_id = int(record["research_run_id"])
        rows = conn.execute(
            """SELECT d.*,ms.captured_at AS actual_cut,ms.provider,
                      ms.underlying AS actual_underlying
               FROM unified_candidate_decisions_v1 AS d
               JOIN market_snapshots AS ms ON ms.id=d.snapshot_id
               WHERE d.research_run_id=? ORDER BY d.id DESC LIMIT ?""",
            (run_id, MAX_LEDGER_ROWS + 1),
        ).fetchall()
        if len(rows) > MAX_LEDGER_ROWS:
            raise ValueError("UNIFIED_BOOK_TOO_LARGE_TO_DISPLAY_COMPLETELY")
        summaries = []
        freshest = None
        for r in rows:
            raw = str(r["input_json"])
            if hashlib.sha256(raw.encode("utf-8")).hexdigest() != r["input_sha256"]:
                raise ValueError("FROZEN_DECISION_INPUT_TAMPERED")
            payload = json.loads(raw)
            if (
                payload["snapshot"] != r["snapshot_id"]
                or payload["run"] != r["research_run_id"]
                or payload["underlying"] != r["underlying"]
                or payload["expiration"] != r["expiration"]
                or payload["structure"]["strategy_id"] != r["strategy_id"]
                or payload["structure"]["reference"] != r["source_reference"]
                or r["provider"] != "THETADATA"
                or r["actual_underlying"] != r["underlying"]
                or _time(r["actual_cut"]) != _time(r["asof_at"])
            ):
                raise ValueError("FROZEN_DECISION_IDENTITY_MISMATCH")
            cut = _time(r["asof_at"])
            freshest = max(freshest, cut) if freshest else cut
            age = now - cut
            blockers = list(json.loads(r["blockers_json"]))
            state = str(r["state"])
            if state == MANUAL_REQUOTE:
                if r["provenance_tier"] != "PROSPECTIVE_CONTROLLED_MODEL":
                    state = NO_TRADE
                    blockers.append("UNPROVEN_MODEL_NOT_TRADE_AUTHORITY")
                elif not timedelta(0) <= age <= SOURCE_MAX_AGE:
                    state = NO_TRADE
                    blockers.append("FROZEN_QUOTE_EXPIRED")
            if state != MANUAL_REQUOTE and not blockers:
                blockers.append("RESEARCH_NOT_TRADE_AUTHORITY")
            score = (
                Decimal(str(r["risk_adjusted_score"]))
                if r["risk_adjusted_score"] is not None else None
            )
            value = (
                Decimal(str(r["conservative_net_ev_usd"]))
                if r["conservative_net_ev_usd"] is not None else None
            )
            risk = (
                Decimal(str(r["modeled_all_in_risk_usd"]))
                if r["modeled_all_in_risk_usd"] is not None else None
            )
            ev_inputs = payload["scored_result"].get("model_net_ev_usd", ())
            model_evs = tuple(
                (str(name),None if ev is None else Decimal(str(ev)))
                for name,ev in ev_inputs
            )
            summaries.append(RankedOpportunity(
                snapshot_id=int(r["snapshot_id"]),
                underlying=str(r["underlying"]),
                expiration=str(r["expiration"]),
                strategy_id=str(r["strategy_id"]),
                source_reference=str(r["source_reference"]),
                lane=str(r["lane"]),
                state=state,
                rank=int(r["rank"]) if state == MANUAL_REQUOTE
                     and r["rank"] is not None else None,
                conservative_net_ev_usd=value,
                risk_adjusted_score=score,
                assumed_worst_loss_usd=risk,
                confirming_model_groups=int(r["confirming_model_groups"]),
                opposing_model_groups=int(r["opposing_model_groups"]),
                missing_evidence=tuple(sorted(set(blockers))),
                model_net_ev_usd=model_evs,
                broker_order_authority=False,
            ))
        permitted = sorted(
            (s for s in summaries if s.state == MANUAL_REQUOTE),
            key=lambda x: (x.rank is None, x.rank or 999),
        )
        blocked = sorted(
            (s for s in summaries if s.state != MANUAL_REQUOTE),
            key=lambda x: (x.underlying,x.expiration,x.strategy_id),
        )
        decision = MarketDecision(
            state=MANUAL_REQUOTE if permitted else NO_TRADE,
            top=permitted[0] if permitted else None,
            opportunities=tuple([*permitted,*blocked]),
            rejected_count=len(blocked),
            provisional_count=len(permitted),
        )
        return FrozenBookReport(
            decision=decision,
            latest_snapshot_at=freshest.isoformat().replace("+00:00","Z")
            if freshest else None,
            last_run_id=run_id,records=len(rows),
        )
    finally:
        conn.close()
