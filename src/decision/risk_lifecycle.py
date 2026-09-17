from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from typing import Any

from src.database.repository import get_connection


RISK_PLAN_VERSION = "SHADOW_INTRINSIC_RISK_PLAN_V1"
ASSESSMENT_VERSION = "SHADOW_INTRINSIC_RISK_ASSESSMENT_V1"


@dataclass(frozen=True)
class FrozenRiskPlan:
    id: int
    candidate_id: int
    created_at: str
    recorded_at: str
    prospectivity_state: str
    plan_version: str
    actor: str
    max_defined_loss_eur_minor: int
    risk_basis_eur_minor: int
    stop_loss_fraction: float | None
    time_stop_at: str | None
    thesis_invalidation_rule: str | None
    event_stop_rule: str | None
    entry_assumption: dict[str, Any]
    notes: str | None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RiskAssessment:
    candidate_id: int
    observed_at: str
    price_stop_state: str
    time_stop_state: str
    thesis_stop_state: str
    event_stop_state: str
    overall_state: str
    loss_fraction_risk_basis: float | None
    reason_codes: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _aware(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Timestamp must be timezone-aware.")
    return parsed


def _same_instant(first: str, second: str) -> bool:
    return (
        _aware(first).astimezone(timezone.utc)
        == _aware(second).astimezone(timezone.utc)
    )


def get_frozen_risk_plan(
    *, candidate_id: int, db_path=None
) -> FrozenRiskPlan | None:
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            """
            SELECT p.*, rec.recorded_at, rec.prospectivity_state
            FROM shadow_intrinsic_risk_plans_v1 AS p
            JOIN shadow_intrinsic_risk_plan_recordings_v1 AS rec
              ON rec.risk_plan_id = p.id
            WHERE p.candidate_id = ?;
            """,
            (candidate_id,),
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        return None

    try:
        entry_assumption = json.loads(row["entry_assumption_json"])
    except (TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            "Frozen risk plan contains invalid entry-assumption JSON."
        ) from exc
    if not isinstance(entry_assumption, dict):
        raise RuntimeError(
            "Frozen risk plan entry assumption must be a JSON object."
        )

    return FrozenRiskPlan(
        id=int(row["id"]),
        candidate_id=int(row["candidate_id"]),
        created_at=str(row["created_at"]),
        recorded_at=str(row["recorded_at"]),
        prospectivity_state=str(row["prospectivity_state"]),
        plan_version=str(row["plan_version"]),
        actor=str(row["actor"]),
        max_defined_loss_eur_minor=int(row["max_defined_loss_eur_minor"]),
        risk_basis_eur_minor=int(row["risk_basis_eur_minor"]),
        stop_loss_fraction=(
            None
            if row["stop_loss_fraction"] is None
            else float(row["stop_loss_fraction"])
        ),
        time_stop_at=row["time_stop_at"],
        thesis_invalidation_rule=row["thesis_invalidation_rule"],
        event_stop_rule=row["event_stop_rule"],
        entry_assumption=entry_assumption,
        notes=row["notes"],
    )


def create_frozen_risk_plan(
    *,
    candidate_id: int,
    max_defined_loss_eur_minor: int,
    risk_basis_eur_minor: int | None = None,
    reserved_risk_eur_minor: int | None = None,
    stop_loss_fraction: float | None = None,
    time_stop_at: str | None = None,
    thesis_invalidation_rule: str | None = None,
    event_stop_rule: str | None = None,
    entry_assumption: dict[str, Any] | None = None,
    actor: str = "OPERATOR",
    notes: str | None = None,
    created_at: str | None = None,
    db_path=None,
) -> FrozenRiskPlan:
    """Freeze an intrinsic candidate risk plan.

    `risk_basis_eur_minor` is the loss denominator used by the candidate's
    predeclared stop logic. It is a property of the research trade definition,
    not an account reservation and not an affordability test.

    `reserved_risk_eur_minor` is accepted temporarily as a compatibility alias
    for callers from the pre-V29 API. It has no bankroll/account semantics and
    cannot impose a ceiling.
    """
    if max_defined_loss_eur_minor < 0:
        raise ValueError("Defined maximum loss cannot be negative.")

    if risk_basis_eur_minor is None:
        risk_basis_eur_minor = reserved_risk_eur_minor
    elif (
        reserved_risk_eur_minor is not None
        and int(reserved_risk_eur_minor) != int(risk_basis_eur_minor)
    ):
        raise ValueError(
            "risk_basis_eur_minor conflicts with the compatibility alias."
        )

    if risk_basis_eur_minor is None:
        risk_basis_eur_minor = max_defined_loss_eur_minor

    risk_basis_eur_minor = int(risk_basis_eur_minor)
    if risk_basis_eur_minor <= 0:
        raise ValueError("Intrinsic risk basis must be positive.")
    if max_defined_loss_eur_minor > risk_basis_eur_minor:
        raise ValueError(
            "Defined maximum loss cannot exceed the intrinsic risk basis."
        )
    if (
        stop_loss_fraction is not None
        and not 0 < float(stop_loss_fraction) <= 1
    ):
        raise ValueError("stop_loss_fraction must be in (0,1].")
    if not str(actor).strip():
        raise ValueError("Risk-plan actor cannot be blank.")

    if time_stop_at is not None:
        _aware(time_stop_at)

    created_at = created_at or datetime.now(timezone.utc).isoformat(
        timespec="milliseconds"
    ).replace("+00:00", "Z")
    created_dt = _aware(created_at)

    if entry_assumption is None:
        entry_assumption = {}
    if not isinstance(entry_assumption, dict):
        raise ValueError("entry_assumption must be a dictionary.")

    conn = get_connection(db_path)
    try:
        candidate = conn.execute(
            "SELECT surfaced_at FROM shadow_candidates WHERE id = ?;",
            (candidate_id,),
        ).fetchone()
        if candidate is None:
            raise ValueError(f"Unknown shadow candidate {candidate_id}.")
        if created_dt < _aware(str(candidate["surfaced_at"])):
            raise ValueError("Risk plan cannot predate the candidate.")

        existing_mark = conn.execute(
            """
            SELECT 1
            FROM shadow_mark_observations
            WHERE candidate_id = ?
            LIMIT 1;
            """,
            (candidate_id,),
        ).fetchone()
        if existing_mark is not None:
            raise ValueError(
                "Prospective risk plan refused: candidate already has shadow marks."
            )

        with conn:
            conn.execute(
                """
                INSERT INTO shadow_intrinsic_risk_plans_v1 (
                    candidate_id, created_at, plan_version, actor,
                    max_defined_loss_eur_minor, risk_basis_eur_minor,
                    stop_loss_fraction, time_stop_at,
                    thesis_invalidation_rule, event_stop_rule,
                    entry_assumption_json, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    candidate_id,
                    created_at,
                    RISK_PLAN_VERSION,
                    actor,
                    max_defined_loss_eur_minor,
                    risk_basis_eur_minor,
                    stop_loss_fraction,
                    time_stop_at,
                    thesis_invalidation_rule,
                    event_stop_rule,
                    json.dumps(entry_assumption, sort_keys=True),
                    notes,
                ),
            )
    finally:
        conn.close()

    plan = get_frozen_risk_plan(candidate_id=candidate_id, db_path=db_path)
    if plan is None:
        raise RuntimeError("Frozen risk plan insert did not persist.")
    if plan.prospectivity_state != "DB_RECORDED_PROSPECTIVE":
        raise RuntimeError(
            "New risk plan did not receive DB-recorded prospective origin evidence."
        )
    return plan


def evaluate_risk_plan(
    plan: FrozenRiskPlan,
    *,
    observed_at: str,
    mark_net_pnl_eur_minor: int | None = None,
    thesis_invalidated: bool | None = None,
    event_risk_active: bool | None = None,
) -> RiskAssessment:
    observed_dt = _aware(observed_at)
    if plan.prospectivity_state != "DB_RECORDED_PROSPECTIVE":
        raise ValueError(
            "Risk assessment refused: risk-plan prospectivity is not DB-verified."
        )
    if observed_dt < _aware(plan.recorded_at):
        raise ValueError(
            "Risk assessment cannot predate the DB-recorded risk plan."
        )

    reasons: list[str] = []
    loss_fraction = None

    if plan.stop_loss_fraction is None:
        price_state = "NOT_CONFIGURED"
    elif mark_net_pnl_eur_minor is None:
        price_state = "UNAVAILABLE"
        reasons.append("PRICE_STOP_INPUT_UNAVAILABLE")
    else:
        loss_fraction = max(
            0.0,
            -float(mark_net_pnl_eur_minor) / plan.risk_basis_eur_minor,
        )
        price_state = (
            "BREACHED"
            if loss_fraction >= plan.stop_loss_fraction
            else "CLEAR"
        )
        if price_state == "BREACHED":
            reasons.append("PRICE_STOP_BREACHED")

    if plan.time_stop_at is None:
        time_state = "NOT_CONFIGURED"
    else:
        time_state = (
            "BREACHED"
            if observed_dt >= _aware(plan.time_stop_at)
            else "CLEAR"
        )
        if time_state == "BREACHED":
            reasons.append("TIME_STOP_BREACHED")

    if not plan.thesis_invalidation_rule:
        thesis_state = "NOT_CONFIGURED"
    elif thesis_invalidated is None:
        thesis_state = "UNAVAILABLE"
        reasons.append("THESIS_STOP_REQUIRES_REVIEW")
    else:
        thesis_state = "BREACHED" if thesis_invalidated else "CLEAR"
        if thesis_state == "BREACHED":
            reasons.append("THESIS_STOP_BREACHED")

    if not plan.event_stop_rule:
        event_state = "NOT_CONFIGURED"
    elif event_risk_active is None:
        event_state = "UNAVAILABLE"
        reasons.append("EVENT_STOP_REQUIRES_REVIEW")
    else:
        event_state = "BREACHED" if event_risk_active else "CLEAR"
        if event_state == "BREACHED":
            reasons.append("EVENT_STOP_BREACHED")

    states = (price_state, time_state, thesis_state, event_state)
    if "BREACHED" in states:
        overall_state = "EXIT_TRIGGERED"
    elif "UNAVAILABLE" in states:
        overall_state = "REVIEW_REQUIRED"
    else:
        overall_state = "CLEAR"

    return RiskAssessment(
        candidate_id=plan.candidate_id,
        observed_at=observed_at,
        price_stop_state=price_state,
        time_stop_state=time_state,
        thesis_stop_state=thesis_state,
        event_stop_state=event_state,
        overall_state=overall_state,
        loss_fraction_risk_basis=loss_fraction,
        reason_codes=tuple(reasons),
    )


def record_risk_assessment(
    *,
    candidate_id: int,
    observed_at: str,
    shadow_mark_id: int | None = None,
    mark_net_pnl_eur_minor: int | None = None,
    thesis_invalidated: bool | None = None,
    event_risk_active: bool | None = None,
    db_path=None,
) -> RiskAssessment:
    plan = get_frozen_risk_plan(candidate_id=candidate_id, db_path=db_path)
    if plan is None:
        raise ValueError(
            f"Candidate {candidate_id} has no frozen intrinsic shadow risk plan."
        )

    evidence: dict[str, Any] = {
        "thesis_invalidated": thesis_invalidated,
        "event_risk_active": event_risk_active,
        "source": (
            "MANUAL_ASSESSMENT"
            if shadow_mark_id is None
            else "PERSISTED_SHADOW_MARK"
        ),
        "account_balance_dependency": False,
    }

    conn = get_connection(db_path)
    try:
        if shadow_mark_id is not None:
            mark = conn.execute(
                """
                SELECT candidate_id, observed_at, estimated_net_pnl_eur_minor
                FROM shadow_mark_observations
                WHERE id = ?;
                """,
                (shadow_mark_id,),
            ).fetchone()
            if mark is None:
                raise ValueError(f"Unknown shadow mark {shadow_mark_id}.")
            if int(mark["candidate_id"]) != candidate_id:
                raise ValueError(
                    "Shadow mark belongs to a different candidate; assessment refused."
                )
            persisted_at = str(mark["observed_at"])
            if not _same_instant(observed_at, persisted_at):
                raise ValueError(
                    "Assessment timestamp must match the referenced persisted shadow mark."
                )
            persisted_pnl = mark["estimated_net_pnl_eur_minor"]
            if (
                mark_net_pnl_eur_minor is not None
                and persisted_pnl is not None
                and int(mark_net_pnl_eur_minor) != int(persisted_pnl)
            ):
                raise ValueError(
                    "Assessment P&L conflicts with the referenced persisted shadow mark."
                )
            if mark_net_pnl_eur_minor is None:
                mark_net_pnl_eur_minor = persisted_pnl
            evidence["shadow_mark_id"] = shadow_mark_id

        assessment = evaluate_risk_plan(
            plan,
            observed_at=observed_at,
            mark_net_pnl_eur_minor=mark_net_pnl_eur_minor,
            thesis_invalidated=thesis_invalidated,
            event_risk_active=event_risk_active,
        )

        with conn:
            conn.execute(
                """
                INSERT INTO shadow_intrinsic_risk_assessments_v1 (
                    risk_plan_id, candidate_id, shadow_mark_id, observed_at,
                    assessment_version, mark_net_pnl_eur_minor,
                    loss_fraction_risk_basis, price_stop_state, time_stop_state,
                    thesis_stop_state, event_stop_state, overall_state,
                    reason_codes_json, evidence_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    plan.id,
                    candidate_id,
                    shadow_mark_id,
                    observed_at,
                    ASSESSMENT_VERSION,
                    mark_net_pnl_eur_minor,
                    assessment.loss_fraction_risk_basis,
                    assessment.price_stop_state,
                    assessment.time_stop_state,
                    assessment.thesis_stop_state,
                    assessment.event_stop_state,
                    assessment.overall_state,
                    json.dumps(assessment.reason_codes),
                    json.dumps(evidence, sort_keys=True),
                ),
            )
    finally:
        conn.close()

    return assessment


def monitor_frozen_risk_plans(*, db_path=None) -> dict[str, int]:
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            """
            SELECT
                p.candidate_id,
                rec.recorded_at AS plan_recorded_at,
                m.id AS mark_id,
                m.observed_at,
                m.estimated_net_pnl_eur_minor
            FROM shadow_intrinsic_risk_plans_v1 AS p
            JOIN shadow_intrinsic_risk_plan_recordings_v1 AS rec
              ON rec.risk_plan_id = p.id
            JOIN shadow_mark_observations AS m
              ON m.candidate_id = p.candidate_id
            LEFT JOIN shadow_intrinsic_risk_assessments_v1 AS a
              ON a.shadow_mark_id = m.id
            WHERE a.id IS NULL
              AND rec.prospectivity_state = 'DB_RECORDED_PROSPECTIVE'
            ORDER BY m.observed_at, m.id;
            """
        ).fetchall()
        without_marks = int(
            conn.execute(
                """
                SELECT COUNT(*)
                FROM shadow_intrinsic_risk_plans_v1 AS p
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM shadow_mark_observations AS m
                    WHERE m.candidate_id = p.candidate_id
                );
                """
            ).fetchone()[0]
        )
    finally:
        conn.close()

    recorded = 0
    retrospective_marks = 0
    for row in rows:
        if _aware(str(row["observed_at"])) < _aware(
            str(row["plan_recorded_at"])
        ):
            retrospective_marks += 1
            continue
        record_risk_assessment(
            candidate_id=int(row["candidate_id"]),
            shadow_mark_id=int(row["mark_id"]),
            observed_at=str(row["observed_at"]),
            mark_net_pnl_eur_minor=row["estimated_net_pnl_eur_minor"],
            db_path=db_path,
        )
        recorded += 1

    return {
        "recorded": recorded,
        "skipped_existing": 0,
        "without_marks": without_marks,
        "retrospective_marks_refused": retrospective_marks,
    }
