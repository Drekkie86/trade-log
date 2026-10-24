"""Append-only prospective market decisions, never retrospective recommendations.

Write the *entire* cross-strategy model input and chosen/rejected outcome
atomically within minutes of the real snapshot cut. No rows are rewritable,
and replaying past stored decisions cannot create new prospective history.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Sequence
from zoneinfo import ZoneInfo

from src.database.repository import get_connection, assert_schema_version
from src.decision.unified_trade_ranker_v1 import (
    MANUAL_REQUOTE, OptionCandidate, rank_market_opportunities,
)
from src.research.massive_underlying_observation_v1 import (
    STOCK_PRICE_SOURCE, MAX_AGE_SECONDS,
)

MAX_FREEZE_LAG = timedelta(minutes=15)
MAX_FREEZE_ROWS = 200
NEW_YORK = ZoneInfo("America/New_York")
VERSION = "UNIFIED_PROSPECTIVE_DECISION_LEDGER_V1"


@dataclass(frozen=True)
class FrozenDecisionReceipt:
    research_run_id: int
    frozen_at: str
    candidate_ids: tuple[int, ...]
    newly_inserted: int
    models_promoted_to_live_trading: int = 0


def _parse_utc(raw: str) -> datetime:
    value = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("NAIVE_OR_MISSING_PROSPECTIVE_TIMESTAMP")
    return value.astimezone(UTC)


def _json(value) -> str:
    def convert(obj):
        if isinstance(obj, Decimal):
            if not obj.is_finite():
                raise ValueError("NONFINITE_PROSPECTIVE_MODEL_INPUT")
            return str(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        raise TypeError(f"UNSERIALIZABLE_PROSPECTIVE_INPUT:{type(obj).__name__}")
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), default=convert,
        ensure_ascii=True, allow_nan=False,
    )


def _stock_source_qualified(snapshot) -> bool:
    if (
        snapshot["provider"] != "THETADATA"
        or snapshot["underlying_price"] is None
        or snapshot["underlying_source"] != "FETCHED"
        or f"stock price source={STOCK_PRICE_SOURCE};"
        not in str(snapshot["notes"] or "")
    ):
        return False
    try:
        px = Decimal(str(snapshot["underlying_price"]))
        age = (
            _parse_utc(snapshot["captured_at"])
            - _parse_utc(snapshot["underlying_at"])
        ).total_seconds()
        return px.is_finite() and px > 0 and 0 <= age <= MAX_AGE_SECONDS
    except (ValueError, TypeError):
        return False


def freeze_market_decisions(
    *,
    research_run_id: int,
    candidates: Sequence[OptionCandidate],
    db_path=None,
) -> FrozenDecisionReceipt:
    """Freeze score, model disagreements, strategy, exact legs and all costs.

    NO_TRADE entries are retained so future studies do not cherry-pick only
    winning trades. This is never an order-placement or P&L operation.
    """
    if not 1 <= len(candidates) <= MAX_FREEZE_ROWS:
        raise ValueError("BOUNDED_CANDIDATE_BATCH_REQUIRED")
    # Read the server clock here. The caller cannot backdate a decision.
    freeze_time = datetime.now(UTC)
    decision = rank_market_opportunities(candidates)
    assessed = {
        (row.snapshot_id, row.underlying, row.expiration,
         row.strategy_id, row.source_reference): row
        for row in decision.opportunities
    }
    if len(assessed) != len(candidates):
        raise ValueError("DECISION_IDENTITY_CONFLICT")
    assert_schema_version(db_path)

    conn = get_connection(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        inputs = []
        for candidate in candidates:
            if candidate.lane not in {"MAIN", "CASINO"}:
                raise ValueError("UNRECOGNIZED_CAPITAL_LANE")
            if not candidate.structure.reference:
                raise ValueError("FROZEN_SOURCE_REFERENCE_REQUIRED")
            key = (
                candidate.snapshot_id, candidate.underlying,
                candidate.expiration, candidate.structure.strategy_id,
                candidate.structure.reference,
            )
            row = assessed[key]
            snapshot = conn.execute(
                """SELECT id,research_run_id,provider,underlying,captured_at,
                          underlying_at,underlying_price,underlying_source,notes
                   FROM market_snapshots WHERE id=?""",
                (candidate.snapshot_id,),
            ).fetchone()
            if snapshot is None:
                raise ValueError("SOURCE_SNAPSHOT_NOT_FOUND")
            if (
                int(snapshot["research_run_id"] or -1) != research_run_id
                or str(snapshot["underlying"]) != candidate.underlying
            ):
                raise ValueError("SNAPSHOT_RESEARCH_IDENTITY_MISMATCH")
            asof = _parse_utc(snapshot["captured_at"])
            if not (asof <= freeze_time <= asof + MAX_FREEZE_LAG):
                raise ValueError("CANDIDATE_NOT_FROZEN_PROSPECTIVELY")
            if _parse_utc(candidate.structure.decision_at) != asof:
                raise ValueError("STRUCTURE_ASOF_SNAPSHOT_MISMATCH")
            try:
                expiry = datetime.fromisoformat(candidate.expiration).date()
                if expiry < freeze_time.astimezone(NEW_YORK).date():
                    raise ValueError("EXPIRY_BEFORE_FREEZE")
            except (TypeError, ValueError):
                raise ValueError("INVALID_OR_PAST_EXPIRY")
            if not _stock_source_qualified(snapshot):
                raise ValueError("INDEPENDENT_STOCK_REFERENCE_NOT_EVIDENCED")

            source_ids = [
                int(leg.source_id) for leg in candidate.structure.legs
                if leg.source_id is not None
            ]
            if len(source_ids) != len(candidate.structure.legs):
                raise ValueError("SOURCE_OPTION_QUOTE_IDS_REQUIRED")
            if len(set(source_ids)) != len(source_ids):
                # A two-leg 1x2 structure must represent one leg with
                # quantity=2, not multiple duplicate source identities.
                raise ValueError("REUSED_SOURCE_QUOTE_ID")
            found = conn.execute(
                "SELECT COUNT(*) FROM option_quotes WHERE snapshot_id=? "
                f"AND id IN ({','.join('?' for _ in source_ids)})",
                (candidate.snapshot_id, *source_ids),
            ).fetchone()[0]
            if int(found) != len(source_ids):
                raise ValueError("SOURCE_LEGS_NOT_IN_SAME_SNAPSHOT")
            forecast_inputs = [
                {
                    "model_id": m.model_id,
                    "dependence_group": m.dependence_group,
                    "thesis": asdict(m.thesis),
                }
                for m in candidate.model_inputs
            ]
            if any(
                _parse_utc(m.thesis.frozen_at) > asof
                or (
                    m.thesis.training_cutoff is not None
                    and _parse_utc(m.thesis.training_cutoff)
                    > _parse_utc(m.thesis.frozen_at)
                )
                for m in candidate.model_inputs
            ):
                raise ValueError("FORECAST_AFTER_ASOF_LEAKAGE")
            exit_rules = {m.thesis.exit_rule for m in candidate.model_inputs}
            exit_rule = (
                next(iter(exit_rules))
                if len(exit_rules) == 1 and None not in exit_rules
                else "NOT_ESTABLISHED"
            )
            if row.state == MANUAL_REQUOTE and exit_rule == "NOT_ESTABLISHED":
                raise ValueError("MANUAL_REQUOTE_WITHOUT_EXIT_RULE")
            payload = {
                "version": VERSION,
                "run": research_run_id,
                "snapshot": candidate.snapshot_id,
                "captured_at": snapshot["captured_at"],
                "underlying": candidate.underlying,
                "expiration": candidate.expiration,
                "lane": candidate.lane,
                "structure": asdict(candidate.structure),
                "cost_policy": asdict(candidate.cost_policy),
                "model_inputs": forecast_inputs,
                "scored_result": asdict(row),
            }
            body = _json(payload)
            sha = hashlib.sha256(body.encode("utf-8")).hexdigest()
            inputs.append((
                research_run_id, candidate.snapshot_id,
                candidate.underlying, candidate.expiration, candidate.lane,
                candidate.structure.strategy_id,
                snapshot["captured_at"],
                freeze_time.isoformat().replace("+00:00", "Z"),
                candidate.structure.reference, sha, body, decision.version,
                row.state, row.rank,
                None if row.conservative_net_ev_usd is None
                else str(row.conservative_net_ev_usd),
                None if row.assumed_worst_loss_usd is None
                else str(row.assumed_worst_loss_usd),
                None if row.risk_adjusted_score is None
                else str(row.risk_adjusted_score),
                row.confirming_model_groups, row.opposing_model_groups,
                _json(row.missing_evidence),
                _json([
                    {"model_id": m.model_id,
                     "dependence_group": m.dependence_group,
                     "thesis_id": m.thesis.thesis_id,
                     "forecast_source": m.thesis.forecast_source,
                     "forecast_version": m.thesis.forecast_model_version}
                    for m in candidate.model_inputs
                ]),
                exit_rule, "UNPROVEN_MODEL",
            ))
        ids = []
        inserted = 0
        for data in inputs:
            cur = conn.execute(
                """INSERT INTO unified_candidate_decisions_v1
                  (research_run_id,snapshot_id,underlying,expiration,lane,
                   strategy_id,asof_at,frozen_at,source_reference,input_sha256,
                   input_json,model_version,state,rank,
                   conservative_net_ev_usd,modeled_all_in_risk_usd,
                   risk_adjusted_score,confirming_model_groups,
                   opposing_model_groups,blockers_json,forecast_lineage_json,
                   exit_rule,provenance_tier)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(input_sha256) DO NOTHING""",
                data,
            )
            inserted += cur.rowcount
            record = conn.execute(
                "SELECT id,input_json FROM unified_candidate_decisions_v1 "
                "WHERE input_sha256=?", (data[9],),
            ).fetchone()
            if record is None or record["input_json"] != data[10]:
                raise ValueError("IMMUTABLE_DECISION_DIGEST_COLLISION")
            ids.append(int(record["id"]))
        conn.commit()
        return FrozenDecisionReceipt(
            research_run_id=research_run_id,
            frozen_at=freeze_time.isoformat().replace("+00:00", "Z"),
            candidate_ids=tuple(ids),
            newly_inserted=inserted,
        )
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
