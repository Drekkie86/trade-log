from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import json
from typing import Any
from zoneinfo import ZoneInfo

from src.database.repository import get_connection
from src.research.shadow_outcome_collector_v2 import (
    _entry_cashflow_usd_minor,
    _quote_for_leg,
)

UTC = ZoneInfo("UTC")

REPLAY_VERSION = "WALLET_POLICY_REMOVAL_REPLAY_V1"
LEGACY_POLICY_VERSION = "SIZING_POLICY_V1_FIXED_500_EUR_ONE_UNIT"
TARGET_POLICY_VERSION = "INTRINSIC_DEFINED_RISK_V1"
NO_LOOKAHEAD_CONTRACT = (
    "LEGACY_WALLET_BLOCK_PROVES_ALL_PRECEDING_ENTRY_QUALITY_GATES_PASSED_V1"
)
RECOVERY_METHOD = "EXPIRY_INTRINSIC_FROM_STORED_UNDERLYING_SNAPSHOT_V1"

WALLET_ONLY_REASON_CODES = frozenset(
    {
        "ONE_UNIT_EXCEEDS_EUR_500_BANKROLL",
        "ACTIVE_PORTFOLIO_EXCEEDS_EUR_500_BANKROLL",
    }
)


class HistoricalReplayError(RuntimeError):
    pass


@dataclass(frozen=True)
class HistoricalReplayResult:
    replay_run_id: int
    wallet_blocks_found: int
    policy_replays_written: int
    would_admit_count: int
    would_block_count: int
    replay_marks_written: int
    complete_replay_marks: int
    incomplete_replay_marks: int
    outcome_recoveries_written: int
    recovered_outcomes: int
    unresolved_outcomes: int
    pending_expiration_count: int


def _now_utc() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _parse_json(value: Any, *, field: str) -> dict[str, Any]:
    try:
        payload = json.loads(str(value))
    except (json.JSONDecodeError, TypeError) as exc:
        raise HistoricalReplayError(f"Invalid {field} JSON.") from exc
    if not isinstance(payload, dict):
        raise HistoricalReplayError(f"{field} must contain a JSON object.")
    return payload


def _get_or_create_replay_run(*, db_path=None) -> int:
    conn = get_connection(db_path)
    try:
        existing = conn.execute(
            """
            SELECT id
            FROM historical_replay_runs_v1
            WHERE replay_version = ?;
            """,
            (REPLAY_VERSION,),
        ).fetchone()
        if existing is not None:
            return int(existing["id"])

        scope = {
            "source_population": "legacy shadow admission decisions",
            "eligible_original_decisions": sorted(WALLET_ONLY_REASON_CODES),
            "policy_replay_population": "RETROSPECTIVE_POLICY_REPLAY",
            "original_admission_population": "PROSPECTIVE_ORIGINAL",
            "target_policy": TARGET_POLICY_VERSION,
            "current_entry_evidence_queries_allowed": False,
            "current_fx_queries_allowed": False,
            "broker_orders_allowed": False,
            "validated_package_outcome_created": False,
        }
        with conn:
            cursor = conn.execute(
                """
                INSERT INTO historical_replay_runs_v1(
                    replay_version,
                    created_at,
                    source_policy_version,
                    target_policy_version,
                    no_lookahead_contract,
                    scope_json,
                    notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    REPLAY_VERSION,
                    _now_utc(),
                    LEGACY_POLICY_VERSION,
                    TARGET_POLICY_VERSION,
                    NO_LOOKAHEAD_CONTRACT,
                    _json(scope),
                    (
                        "Historical research reconstruction only. Original "
                        "prospective decisions remain unchanged."
                    ),
                ),
            )
        return int(cursor.lastrowid)
    finally:
        conn.close()


def _wallet_only_blocks(*, db_path=None) -> list[dict[str, Any]]:
    """Load only immutable legacy decisions blocked by the wallet ceiling.

    The source policy evaluated universe, quote and Greek evidence before the
    two wallet checks. Therefore these reason codes are sufficient historical
    proof that the preceding entry-quality gates passed at decision time. This
    function deliberately does not inspect today's latest availability rows or
    fetch current FX.
    """
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            """
            SELECT
                sad.*,
                ssp.research_run_id AS proposal_research_run_id,
                ssp.underlying,
                ssp.expiration,
                ssp.structure_json,
                ssp.entry_pricing_json,
                rr.us_session_date AS proposal_session_date,
                fx.rate AS original_eur_to_usd
            FROM shadow_admission_decisions AS sad
            JOIN shadow_structure_proposals AS ssp
              ON ssp.id = sad.proposal_id
            JOIN research_runs AS rr
              ON rr.id = ssp.research_run_id
            JOIN fx_observations AS fx
              ON fx.id = sad.fx_observation_id
            WHERE sad.decision = 'BLOCKED'
              AND sad.candidate_id IS NULL
              AND sad.sizing_policy_version = ?
              AND sad.reason_code IN (?, ?)
            ORDER BY sad.id;
            """,
            (
                LEGACY_POLICY_VERSION,
                "ONE_UNIT_EXCEEDS_EUR_500_BANKROLL",
                "ACTIVE_PORTFOLIO_EXCEEDS_EUR_500_BANKROLL",
            ),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _persist_policy_replay(
    *, replay_run_id: int, source: dict[str, Any], db_path=None
) -> tuple[int, bool, str]:
    source_id = int(source["id"])
    conn = get_connection(db_path)
    try:
        existing = conn.execute(
            """
            SELECT id, counterfactual_decision
            FROM historical_policy_replay_v1
            WHERE replay_run_id = ?
              AND original_admission_decision_id = ?;
            """,
            (replay_run_id, source_id),
        ).fetchone()
        if existing is not None:
            return (
                int(existing["id"]),
                False,
                str(existing["counterfactual_decision"]),
            )

        max_loss_usd = int(source["proposal_max_loss_usd_minor"])
        max_loss_eur = int(source["converted_max_loss_eur_minor"])
        if max_loss_usd <= 0 or max_loss_eur <= 0:
            decision = "WOULD_BLOCK"
            reason = "TARGET_POLICY_NON_POSITIVE_DEFINED_MAX_LOSS"
        else:
            decision = "WOULD_ADMIT"
            reason = "LEGACY_WALLET_ONLY_BLOCK_REMOVED"

        evidence = {
            "replay_version": REPLAY_VERSION,
            "population": "RETROSPECTIVE_POLICY_REPLAY",
            "original_decision_id": source_id,
            "original_proposal_id": int(source["proposal_id"]),
            "original_fx_observation_id": int(source["fx_observation_id"]),
            "original_policy_version": str(source["sizing_policy_version"]),
            "original_cost_model_version": str(source["cost_model_version"]),
            "original_reason_code": str(source["reason_code"]),
            "original_decided_at": str(source["decided_at"]),
            "no_lookahead": {
                "contract": NO_LOOKAHEAD_CONTRACT,
                "basis": (
                    "In the frozen legacy admission implementation, universe, "
                    "Theta quote and Theta Greek gates were evaluated before "
                    "the wallet-only gates. A wallet-only block therefore "
                    "proves those preceding gates passed at decision time."
                ),
                "current_entry_evidence_queried": False,
                "current_fx_queried": False,
                "future_outcome_data_used_for_admission": False,
            },
            "economics": {
                "source": "IMMUTABLE_ORIGINAL_ADMISSION_DECISION",
                "proposal_max_loss_usd_minor": max_loss_usd,
                "estimated_cost_usd_minor": int(source["estimated_cost_usd_minor"]),
                "intrinsic_risk_usd_minor": int(source["reserved_risk_usd_minor"]),
                "converted_max_loss_eur_minor": max_loss_eur,
                "estimated_cost_eur_minor": int(source["estimated_cost_eur_minor"]),
                "intrinsic_risk_eur_minor": int(source["reserved_risk_eur_minor"]),
            },
            "research_only": True,
            "broker_order_created": False,
        }

        with conn:
            cursor = conn.execute(
                """
                INSERT INTO historical_policy_replay_v1(
                    replay_run_id,
                    original_admission_decision_id,
                    proposal_id,
                    original_fx_observation_id,
                    original_decision,
                    original_reason_code,
                    original_decided_at,
                    counterfactual_decision,
                    counterfactual_reason_code,
                    target_risk_policy_version,
                    proposal_max_loss_usd_minor,
                    estimated_cost_usd_minor,
                    intrinsic_risk_usd_minor,
                    converted_max_loss_eur_minor,
                    estimated_cost_eur_minor,
                    intrinsic_risk_eur_minor,
                    evidence_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    replay_run_id,
                    source_id,
                    int(source["proposal_id"]),
                    int(source["fx_observation_id"]),
                    str(source["decision"]),
                    str(source["reason_code"]),
                    str(source["decided_at"]),
                    decision,
                    reason,
                    TARGET_POLICY_VERSION,
                    max_loss_usd,
                    int(source["estimated_cost_usd_minor"]),
                    int(source["reserved_risk_usd_minor"]),
                    max_loss_eur,
                    int(source["estimated_cost_eur_minor"]),
                    int(source["reserved_risk_eur_minor"]),
                    _json(evidence),
                ),
            )
        return int(cursor.lastrowid), True, decision
    finally:
        conn.close()


def replay_wallet_policy_blocks(
    *, replay_run_id: int, db_path=None
) -> tuple[int, int, int, int]:
    sources = _wallet_only_blocks(db_path=db_path)
    written = 0
    would_admit = 0
    would_block = 0
    for source in sources:
        _, inserted, decision = _persist_policy_replay(
            replay_run_id=replay_run_id,
            source=source,
            db_path=db_path,
        )
        written += int(inserted)
        would_admit += int(decision == "WOULD_ADMIT")
        would_block += int(decision == "WOULD_BLOCK")
    return len(sources), written, would_admit, would_block


def _replay_items(*, replay_run_id: int, db_path=None) -> list[dict[str, Any]]:
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            """
            SELECT
                hpr.id AS policy_replay_id,
                hpr.proposal_id,
                hpr.original_admission_decision_id,
                hpr.original_decided_at,
                hpr.estimated_cost_usd_minor,
                hpr.estimated_cost_eur_minor,
                hpr.original_fx_observation_id,
                ssp.research_run_id AS proposal_research_run_id,
                rr.us_session_date AS proposal_session_date,
                ssp.underlying,
                ssp.expiration,
                ssp.structure_json,
                ssp.entry_pricing_json,
                fx.rate AS entry_eur_to_usd
            FROM historical_policy_replay_v1 AS hpr
            JOIN shadow_structure_proposals AS ssp
              ON ssp.id = hpr.proposal_id
            JOIN research_runs AS rr
              ON rr.id = ssp.research_run_id
            JOIN fx_observations AS fx
              ON fx.id = hpr.original_fx_observation_id
            WHERE hpr.replay_run_id = ?
              AND hpr.counterfactual_decision = 'WOULD_ADMIT'
            ORDER BY hpr.id;
            """,
            (replay_run_id,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _subsequent_snapshots(
    *, item: dict[str, Any], db_path=None
) -> list[dict[str, Any]]:
    """Return one Theta snapshot per later research run through expiration."""
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            """
            WITH ranked AS (
                SELECT
                    ms.*,
                    rr.us_session_date,
                    COALESCE(rr.ended_at, rr.started_at) AS run_at,
                    ROW_NUMBER() OVER (
                        PARTITION BY rr.id
                        ORDER BY ms.id DESC
                    ) AS rn
                FROM market_snapshots AS ms
                JOIN research_runs AS rr
                  ON rr.id = ms.research_run_id
                WHERE ms.provider = 'THETADATA'
                  AND ms.underlying = ?
                  AND rr.us_session_date <= ?
                  AND rr.id > ?
                  AND COALESCE(rr.ended_at, rr.started_at) >= ?
            )
            SELECT *
            FROM ranked
            WHERE rn = 1
            ORDER BY us_session_date, research_run_id;
            """,
            (
                str(item["underlying"]),
                str(item["expiration"]),
                int(item["proposal_research_run_id"]),
                str(item["original_decided_at"]),
            ),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _persist_replay_mark(
    *,
    item: dict[str, Any],
    snapshot: dict[str, Any],
    quality_state: str,
    structure_mark_usd_minor: int | None,
    gross_pnl_usd_minor: int | None,
    estimated_net_pnl_usd_minor: int | None,
    gross_pnl_eur_minor: int | None,
    estimated_net_pnl_eur_minor: int | None,
    evidence: dict[str, Any],
    db_path=None,
) -> bool:
    conn = get_connection(db_path)
    try:
        existing = conn.execute(
            """
            SELECT id
            FROM historical_replay_marks_v1
            WHERE policy_replay_id = ?
              AND research_run_id = ?;
            """,
            (
                int(item["policy_replay_id"]),
                int(snapshot["research_run_id"]),
            ),
        ).fetchone()
        if existing is not None:
            return False

        with conn:
            conn.execute(
                """
                INSERT INTO historical_replay_marks_v1(
                    policy_replay_id,
                    proposal_id,
                    research_run_id,
                    snapshot_id,
                    observed_at,
                    quality_state,
                    structure_mark_usd_minor,
                    gross_pnl_usd_minor,
                    estimated_net_pnl_usd_minor,
                    gross_pnl_eur_minor,
                    estimated_net_pnl_eur_minor,
                    evidence_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    int(item["policy_replay_id"]),
                    int(item["proposal_id"]),
                    int(snapshot["research_run_id"]),
                    int(snapshot["id"]),
                    str(snapshot["captured_at"]),
                    quality_state,
                    structure_mark_usd_minor,
                    gross_pnl_usd_minor,
                    estimated_net_pnl_usd_minor,
                    gross_pnl_eur_minor,
                    estimated_net_pnl_eur_minor,
                    _json(evidence),
                ),
            )
        return True
    finally:
        conn.close()


def reconstruct_replay_marks(
    *, replay_run_id: int, db_path=None
) -> tuple[int, int, int]:
    written = 0
    complete = 0
    incomplete = 0

    for item in _replay_items(replay_run_id=replay_run_id, db_path=db_path):
        try:
            structure = _parse_json(item["structure_json"], field="structure")
            entry_pricing = _parse_json(
                item["entry_pricing_json"], field="entry pricing"
            )
            entry_cashflow = _entry_cashflow_usd_minor(
                structure=structure,
                entry_pricing=entry_pricing,
            )
            entry_error = None
        except Exception as exc:  # persisted as explicit unavailable evidence
            structure = {"legs": []}
            entry_cashflow = None
            entry_error = f"{type(exc).__name__}: {exc}"

        for snapshot in _subsequent_snapshots(item=item, db_path=db_path):
            base_evidence = {
                "replay_version": REPLAY_VERSION,
                "population": "RETROSPECTIVE_POLICY_REPLAY",
                "policy_replay_id": int(item["policy_replay_id"]),
                "original_decision_id": int(item["original_admission_decision_id"]),
                "original_decided_at": str(item["original_decided_at"]),
                "snapshot_id": int(snapshot["id"]),
                "snapshot_research_run_id": int(snapshot["research_run_id"]),
                "snapshot_session_date": str(snapshot["us_session_date"]),
                "no_lookahead_admission_contract": NO_LOOKAHEAD_CONTRACT,
                "measurement_role": "RETROSPECTIVE_CONSERVATIVE_LIQUIDATION_REPLAY",
                "outcome_eligible": False,
            }

            if entry_cashflow is None:
                evidence = dict(base_evidence)
                evidence["reason"] = "ENTRY_PRICING_UNAVAILABLE"
                evidence["entry_error"] = entry_error
                inserted = _persist_replay_mark(
                    item=item,
                    snapshot=snapshot,
                    quality_state="ENTRY_PRICING_UNAVAILABLE",
                    structure_mark_usd_minor=None,
                    gross_pnl_usd_minor=None,
                    estimated_net_pnl_usd_minor=None,
                    gross_pnl_eur_minor=None,
                    estimated_net_pnl_eur_minor=None,
                    evidence=evidence,
                    db_path=db_path,
                )
                written += int(inserted)
                incomplete += int(inserted)
                continue

            liquidation_cashflow_usd = 0.0
            leg_evidence: list[dict[str, Any]] = []
            all_legs_complete = True

            for leg in structure.get("legs", []):
                quote = _quote_for_leg(
                    snapshot_id=int(snapshot["id"]),
                    expiration=str(item["expiration"]),
                    right=str(leg["right"]),
                    strike=float(leg["strike"]),
                    db_path=db_path,
                )
                if quote is None:
                    all_legs_complete = False
                    leg_evidence.append(
                        {
                            "strike": leg.get("strike"),
                            "right": leg.get("right"),
                            "side": leg.get("side"),
                            "state": "QUOTE_MISSING",
                        }
                    )
                    continue

                bid = quote["bid"]
                ask = quote["ask"]
                if (
                    bid is None
                    or ask is None
                    or float(bid) < 0
                    or float(ask) < float(bid)
                ):
                    all_legs_complete = False
                    leg_evidence.append(
                        {
                            "option_quote_id": int(quote["id"]),
                            "strike": leg.get("strike"),
                            "right": leg.get("right"),
                            "side": leg.get("side"),
                            "bid": bid,
                            "ask": ask,
                            "state": "QUOTE_INVALID",
                        }
                    )
                    continue

                side = str(leg["side"])
                quantity = int(leg["quantity"])
                multiplier = float(leg["shares_per_contract"])
                liquidation_price = (
                    float(bid) if side == "BUY" else float(ask)
                )
                signed = 1.0 if side == "BUY" else -1.0
                liquidation_cashflow_usd += (
                    signed * quantity * multiplier * liquidation_price
                )
                leg_evidence.append(
                    {
                        "option_quote_id": int(quote["id"]),
                        "strike": float(leg["strike"]),
                        "right": str(leg["right"]),
                        "side": side,
                        "quantity": quantity,
                        "bid": float(bid),
                        "ask": float(ask),
                        "liquidation_price": liquidation_price,
                        "quote_at": quote["quote_at"],
                        "state": "COMPLETE",
                    }
                )

            evidence = dict(base_evidence)
            evidence["pricing_basis"] = (
                "CONSERVATIVE_LIQUIDATION_LONG_BID_SHORT_ASK"
            )
            evidence["entry_cashflow_usd_minor"] = entry_cashflow
            evidence["leg_evidence"] = leg_evidence

            if not all_legs_complete or not leg_evidence:
                inserted = _persist_replay_mark(
                    item=item,
                    snapshot=snapshot,
                    quality_state="INCOMPLETE_LEG_MARK",
                    structure_mark_usd_minor=None,
                    gross_pnl_usd_minor=None,
                    estimated_net_pnl_usd_minor=None,
                    gross_pnl_eur_minor=None,
                    estimated_net_pnl_eur_minor=None,
                    evidence=evidence,
                    db_path=db_path,
                )
                written += int(inserted)
                incomplete += int(inserted)
                continue

            structure_mark = int(round(liquidation_cashflow_usd * 100))
            gross_usd = int(entry_cashflow) + structure_mark
            net_usd = gross_usd - int(item["estimated_cost_usd_minor"])
            rate = float(item["entry_eur_to_usd"])
            gross_eur = int(round(gross_usd / rate))
            net_eur = int(round(net_usd / rate))

            inserted = _persist_replay_mark(
                item=item,
                snapshot=snapshot,
                quality_state="COMPLETE_RECONSTRUCTED_CONSERVATIVE_LIQUIDATION",
                structure_mark_usd_minor=structure_mark,
                gross_pnl_usd_minor=gross_usd,
                estimated_net_pnl_usd_minor=net_usd,
                gross_pnl_eur_minor=gross_eur,
                estimated_net_pnl_eur_minor=net_eur,
                evidence=evidence,
                db_path=db_path,
            )
            written += int(inserted)
            complete += int(inserted)

    return written, complete, incomplete


def _latest_completed_session_date(*, db_path=None) -> str | None:
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            """
            SELECT MAX(us_session_date) AS session_date
            FROM research_runs
            WHERE status = 'COMPLETED';
            """
        ).fetchone()
        return None if row is None else row["session_date"]
    finally:
        conn.close()


def _original_candidate_sources(*, db_path=None) -> list[dict[str, Any]]:
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            """
            SELECT
                sad.candidate_id AS source_candidate_id,
                sad.proposal_id,
                sad.fx_observation_id AS entry_fx_observation_id,
                sad.estimated_cost_usd_minor,
                sad.estimated_cost_eur_minor,
                sad.decided_at AS source_timestamp,
                fx.rate AS entry_eur_to_usd,
                ssp.underlying,
                ssp.expiration,
                ssp.structure_json,
                ssp.entry_pricing_json
            FROM shadow_admission_decisions AS sad
            JOIN shadow_structure_proposals AS ssp
              ON ssp.id = sad.proposal_id
            JOIN fx_observations AS fx
              ON fx.id = sad.fx_observation_id
            WHERE sad.decision = 'ADMITTED'
              AND sad.candidate_id IS NOT NULL
            ORDER BY sad.candidate_id;
            """
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _replay_outcome_sources(
    *, replay_run_id: int, db_path=None
) -> list[dict[str, Any]]:
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            """
            SELECT
                hpr.id AS policy_replay_id,
                hpr.proposal_id,
                hpr.original_fx_observation_id AS entry_fx_observation_id,
                hpr.estimated_cost_usd_minor,
                hpr.estimated_cost_eur_minor,
                hpr.original_decided_at AS source_timestamp,
                fx.rate AS entry_eur_to_usd,
                ssp.underlying,
                ssp.expiration,
                ssp.structure_json,
                ssp.entry_pricing_json
            FROM historical_policy_replay_v1 AS hpr
            JOIN shadow_structure_proposals AS ssp
              ON ssp.id = hpr.proposal_id
            JOIN fx_observations AS fx
              ON fx.id = hpr.original_fx_observation_id
            WHERE hpr.replay_run_id = ?
              AND hpr.counterfactual_decision = 'WOULD_ADMIT'
            ORDER BY hpr.id;
            """,
            (replay_run_id,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _expiry_snapshot(
    *, underlying: str, expiration: str, db_path=None
) -> dict[str, Any] | None:
    """Use the last stored underlying observation from the expiry session.

    This is intentionally not called an official settlement price. The exact
    provider and capture timestamp are persisted so later stronger recovery can
    supersede it in a new version without rewriting this evidence.
    """
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            """
            SELECT
                ms.*,
                rr.us_session_date
            FROM market_snapshots AS ms
            JOIN research_runs AS rr
              ON rr.id = ms.research_run_id
            WHERE ms.underlying = ?
              AND rr.us_session_date = ?
              AND ms.underlying_price IS NOT NULL
            ORDER BY ms.captured_at DESC, ms.id DESC
            LIMIT 1;
            """,
            (underlying, expiration),
        ).fetchone()
        return None if row is None else dict(row)
    finally:
        conn.close()


def theoretical_expiry_value_usd_minor(
    *, structure: dict[str, Any], underlying_price: float
) -> int:
    total_usd = 0.0
    for leg in structure.get("legs", []):
        strike = float(leg["strike"])
        right = str(leg["right"]).upper()
        side = str(leg["side"]).upper()
        quantity = int(leg["quantity"])
        multiplier = float(leg["shares_per_contract"])
        if quantity <= 0 or multiplier <= 0:
            raise HistoricalReplayError("Invalid structure quantity or multiplier.")
        if right == "C":
            intrinsic = max(float(underlying_price) - strike, 0.0)
        elif right == "P":
            intrinsic = max(strike - float(underlying_price), 0.0)
        else:
            raise HistoricalReplayError(f"Unsupported option right {right!r}.")
        if side == "BUY":
            signed = 1.0
        elif side == "SELL":
            signed = -1.0
        else:
            raise HistoricalReplayError(f"Unsupported structure side {side!r}.")
        total_usd += signed * quantity * multiplier * intrinsic
    return int(round(total_usd * 100))


def _outcome_exists(
    *,
    replay_run_id: int,
    source_population: str,
    source_candidate_id: int | None,
    policy_replay_id: int | None,
    db_path=None,
) -> bool:
    conn = get_connection(db_path)
    try:
        if source_population == "PROSPECTIVE_ORIGINAL":
            row = conn.execute(
                """
                SELECT 1
                FROM historical_outcome_recovery_v1
                WHERE replay_run_id = ?
                  AND source_population = 'PROSPECTIVE_ORIGINAL'
                  AND source_candidate_id = ?
                LIMIT 1;
                """,
                (replay_run_id, source_candidate_id),
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT 1
                FROM historical_outcome_recovery_v1
                WHERE replay_run_id = ?
                  AND source_population = 'RETROSPECTIVE_POLICY_REPLAY'
                  AND policy_replay_id = ?
                LIMIT 1;
                """,
                (replay_run_id, policy_replay_id),
            ).fetchone()
        return row is not None
    finally:
        conn.close()


def _persist_outcome_recovery(
    *,
    replay_run_id: int,
    source_population: str,
    source: dict[str, Any],
    recovery_state: str,
    reason_code: str,
    snapshot: dict[str, Any] | None,
    terminal_structure_value_usd_minor: int | None,
    entry_cashflow_usd_minor: int | None,
    gross_pnl_usd_minor: int | None,
    estimated_net_pnl_usd_minor: int | None,
    gross_pnl_eur_minor: int | None,
    estimated_net_pnl_eur_minor: int | None,
    evidence: dict[str, Any],
    db_path=None,
) -> bool:
    candidate_id = (
        int(source["source_candidate_id"])
        if source_population == "PROSPECTIVE_ORIGINAL"
        else None
    )
    policy_replay_id = (
        int(source["policy_replay_id"])
        if source_population == "RETROSPECTIVE_POLICY_REPLAY"
        else None
    )
    if _outcome_exists(
        replay_run_id=replay_run_id,
        source_population=source_population,
        source_candidate_id=candidate_id,
        policy_replay_id=policy_replay_id,
        db_path=db_path,
    ):
        return False

    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO historical_outcome_recovery_v1(
                    replay_run_id,
                    source_population,
                    source_candidate_id,
                    policy_replay_id,
                    proposal_id,
                    expiration,
                    recovery_state,
                    recovery_method,
                    reason_code,
                    snapshot_id,
                    snapshot_captured_at,
                    snapshot_provider,
                    terminal_underlying_price,
                    terminal_structure_value_usd_minor,
                    entry_cashflow_usd_minor,
                    gross_pnl_usd_minor,
                    estimated_net_pnl_usd_minor,
                    gross_pnl_eur_minor,
                    estimated_net_pnl_eur_minor,
                    entry_fx_observation_id,
                    evidence_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    replay_run_id,
                    source_population,
                    candidate_id,
                    policy_replay_id,
                    int(source["proposal_id"]),
                    str(source["expiration"]),
                    recovery_state,
                    RECOVERY_METHOD,
                    reason_code,
                    None if snapshot is None else int(snapshot["id"]),
                    None if snapshot is None else str(snapshot["captured_at"]),
                    None if snapshot is None else str(snapshot["provider"]),
                    None
                    if snapshot is None
                    else float(snapshot["underlying_price"]),
                    terminal_structure_value_usd_minor,
                    entry_cashflow_usd_minor,
                    gross_pnl_usd_minor,
                    estimated_net_pnl_usd_minor,
                    gross_pnl_eur_minor,
                    estimated_net_pnl_eur_minor,
                    int(source["entry_fx_observation_id"]),
                    _json(evidence),
                ),
            )
        return True
    finally:
        conn.close()


def recover_historical_outcomes(
    *, replay_run_id: int, db_path=None
) -> tuple[int, int, int, int]:
    latest_session = _latest_completed_session_date(db_path=db_path)
    if latest_session is None:
        return 0, 0, 0, 0

    sources: list[tuple[str, dict[str, Any]]] = []
    sources.extend(
        ("PROSPECTIVE_ORIGINAL", source)
        for source in _original_candidate_sources(db_path=db_path)
    )
    sources.extend(
        ("RETROSPECTIVE_POLICY_REPLAY", source)
        for source in _replay_outcome_sources(
            replay_run_id=replay_run_id, db_path=db_path
        )
    )

    written = 0
    recovered = 0
    unresolved = 0
    pending = 0

    for population, source in sources:
        expiration = str(source["expiration"])
        if expiration > latest_session:
            pending += 1
            continue

        snapshot = _expiry_snapshot(
            underlying=str(source["underlying"]),
            expiration=expiration,
            db_path=db_path,
        )
        evidence: dict[str, Any] = {
            "replay_version": REPLAY_VERSION,
            "source_population": population,
            "proposal_id": int(source["proposal_id"]),
            "expiration": expiration,
            "recovery_method": RECOVERY_METHOD,
            "measurement_role": "RETROSPECTIVE_EXPIRY_RECONSTRUCTION",
            "outcome_eligible": False,
            "validated_package_outcome_created": False,
            "guardrail": (
                "Reconstructed historical evidence is kept separate from "
                "VALIDATED_PACKAGE_OUTCOME and never becomes prospective by "
                "being computed later."
            ),
        }

        if snapshot is None:
            evidence["reason"] = "MISSING_EXPIRY_SESSION_UNDERLYING_SNAPSHOT"
            inserted = _persist_outcome_recovery(
                replay_run_id=replay_run_id,
                source_population=population,
                source=source,
                recovery_state="UNRESOLVED",
                reason_code="MISSING_EXPIRY_SESSION_UNDERLYING_SNAPSHOT",
                snapshot=None,
                terminal_structure_value_usd_minor=None,
                entry_cashflow_usd_minor=None,
                gross_pnl_usd_minor=None,
                estimated_net_pnl_usd_minor=None,
                gross_pnl_eur_minor=None,
                estimated_net_pnl_eur_minor=None,
                evidence=evidence,
                db_path=db_path,
            )
            written += int(inserted)
            unresolved += int(inserted)
            continue

        evidence["snapshot"] = {
            "snapshot_id": int(snapshot["id"]),
            "provider": str(snapshot["provider"]),
            "captured_at": str(snapshot["captured_at"]),
            "underlying_price": float(snapshot["underlying_price"]),
            "quality_note": (
                "Last stored underlying observation from the expiry research "
                "session; not asserted to be the official settlement price."
            ),
        }

        try:
            structure = _parse_json(source["structure_json"], field="structure")
            entry_pricing = _parse_json(
                source["entry_pricing_json"], field="entry pricing"
            )
            entry_cashflow = _entry_cashflow_usd_minor(
                structure=structure,
                entry_pricing=entry_pricing,
            )
            terminal_value = theoretical_expiry_value_usd_minor(
                structure=structure,
                underlying_price=float(snapshot["underlying_price"]),
            )
        except Exception as exc:
            evidence["reason"] = "ENTRY_OR_STRUCTURE_RECONSTRUCTION_UNAVAILABLE"
            evidence["error"] = f"{type(exc).__name__}: {exc}"
            inserted = _persist_outcome_recovery(
                replay_run_id=replay_run_id,
                source_population=population,
                source=source,
                recovery_state="UNRESOLVED",
                reason_code="ENTRY_OR_STRUCTURE_RECONSTRUCTION_UNAVAILABLE",
                snapshot=snapshot,
                terminal_structure_value_usd_minor=None,
                entry_cashflow_usd_minor=None,
                gross_pnl_usd_minor=None,
                estimated_net_pnl_usd_minor=None,
                gross_pnl_eur_minor=None,
                estimated_net_pnl_eur_minor=None,
                evidence=evidence,
                db_path=db_path,
            )
            written += int(inserted)
            unresolved += int(inserted)
            continue

        gross_usd = entry_cashflow + terminal_value
        net_usd = gross_usd - int(source["estimated_cost_usd_minor"])
        rate = float(source["entry_eur_to_usd"])
        gross_eur = int(round(gross_usd / rate))
        net_eur = int(round(net_usd / rate))
        evidence["pricing"] = {
            "terminal_payoff_basis": "THEORETICAL_INTRINSIC_AT_STORED_EXPIRY_SESSION_UNDERLYING_PRICE",
            "entry_cashflow_usd_minor": entry_cashflow,
            "terminal_structure_value_usd_minor": terminal_value,
            "estimated_round_trip_cost_usd_minor": int(
                source["estimated_cost_usd_minor"]
            ),
            "entry_fx_observation_id": int(source["entry_fx_observation_id"]),
            "entry_eur_to_usd": rate,
        }

        inserted = _persist_outcome_recovery(
            replay_run_id=replay_run_id,
            source_population=population,
            source=source,
            recovery_state="RECOVERED",
            reason_code="EXPIRY_SESSION_STORED_UNDERLYING_RECONSTRUCTION_AVAILABLE",
            snapshot=snapshot,
            terminal_structure_value_usd_minor=terminal_value,
            entry_cashflow_usd_minor=entry_cashflow,
            gross_pnl_usd_minor=gross_usd,
            estimated_net_pnl_usd_minor=net_usd,
            gross_pnl_eur_minor=gross_eur,
            estimated_net_pnl_eur_minor=net_eur,
            evidence=evidence,
            db_path=db_path,
        )
        written += int(inserted)
        recovered += int(inserted)

    return written, recovered, unresolved, pending


def run_historical_replay_recovery_v1(*, db_path=None) -> HistoricalReplayResult:
    replay_run_id = _get_or_create_replay_run(db_path=db_path)
    found, replay_written, would_admit, would_block = replay_wallet_policy_blocks(
        replay_run_id=replay_run_id,
        db_path=db_path,
    )
    marks_written, complete_marks, incomplete_marks = reconstruct_replay_marks(
        replay_run_id=replay_run_id,
        db_path=db_path,
    )
    (
        outcomes_written,
        outcomes_recovered,
        outcomes_unresolved,
        pending_expiration,
    ) = recover_historical_outcomes(
        replay_run_id=replay_run_id,
        db_path=db_path,
    )
    return HistoricalReplayResult(
        replay_run_id=replay_run_id,
        wallet_blocks_found=found,
        policy_replays_written=replay_written,
        would_admit_count=would_admit,
        would_block_count=would_block,
        replay_marks_written=marks_written,
        complete_replay_marks=complete_marks,
        incomplete_replay_marks=incomplete_marks,
        outcome_recoveries_written=outcomes_written,
        recovered_outcomes=outcomes_recovered,
        unresolved_outcomes=outcomes_unresolved,
        pending_expiration_count=pending_expiration,
    )


def result_as_dict(result: HistoricalReplayResult) -> dict[str, Any]:
    payload = asdict(result)
    payload["replay_version"] = REPLAY_VERSION
    payload["no_lookahead_contract"] = NO_LOOKAHEAD_CONTRACT
    payload["guardrail"] = (
        "Retrospective policy replay and outcome recovery remain separate from "
        "prospective admissions and validated package outcomes."
    )
    return payload
