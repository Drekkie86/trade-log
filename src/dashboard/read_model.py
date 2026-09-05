from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from src.database.repository import (
    EXPECTED_SCHEMA_VERSION,
    resolve_db_path,
)
from src.operations.market_calendar import (
    market_clock_snapshot,
)
from src.operations.runtime_health import (
    assess_daemon_health,
)
from src.providers.thetadata_control import probe_theta_terminal
from src.operations.sqlite_runtime import (
    inspect_database,
    open_readonly_connection,
)


def _row_to_dict(row) -> dict[str, Any] | None:
    if row is None:
        return None
    return dict(row)


def _rows_to_dicts(rows) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


def load_command_deck(
    db_path: str | Path | None = None,
    *,
    now: datetime | None = None,
    include_provider_health: bool = False,
) -> dict[str, Any]:
    path = resolve_db_path(db_path)
    health = inspect_database(path)
    market_clock = market_clock_snapshot(
        now=now
    ).as_dict()
    theta_health: dict[str, Any] = {
        "state": "NOT_PROBED",
        "ready": None,
        "detail": "Provider probe not requested.",
    }

    if not health.exists:
        return {
            "database": health.as_dict(),
            "market_clock": market_clock,
            "theta_health": theta_health,
            "ready": False,
            "reason": "DATABASE_NOT_FOUND",
        }

    if (
        health.schema_version
        != EXPECTED_SCHEMA_VERSION
    ):
        return {
            "database": health.as_dict(),
            "market_clock": market_clock,
            "theta_health": theta_health,
            "ready": False,
            "reason": "SCHEMA_VERSION_MISMATCH",
        }

    if (
        health.quick_check != "ok"
        or health.foreign_key_violation_count != 0
    ):
        return {
            "database": health.as_dict(),
            "market_clock": market_clock,
            "theta_health": theta_health,
            "ready": False,
            "reason": "DATABASE_INTEGRITY_FAILURE",
        }

    if include_provider_health:
        theta_health = probe_theta_terminal().as_dict()

    conn = open_readonly_connection(
        path
    )

    try:
        latest_run = _row_to_dict(
            conn.execute(
                '''
                SELECT
                    id,
                    cohort_id,
                    started_at,
                    ended_at,
                    us_session_date,
                    us_session_state,
                    status,
                    attempted_underlyings,
                    succeeded_underlyings,
                    failed_underlyings,
                    provider_requests_attempted,
                    provider_requests_succeeded,
                    provider_requests_failed
                FROM research_runs
                ORDER BY id DESC
                LIMIT 1;
                '''
            ).fetchone()
        )

        latest_iteration = _row_to_dict(
            conn.execute(
                '''
                SELECT
                    id,
                    scheduled_for,
                    started_at,
                    completed_at,
                    status,
                    research_run_id,
                    proposals_count,
                    admitted_count,
                    blocked_count,
                    outcome_mark_count,
                    error_type,
                    error_message
                FROM research_daemon_iterations
                ORDER BY id DESC
                LIMIT 1;
                '''
            ).fetchone()
        )

        daemon_lock = _row_to_dict(
            conn.execute(
                '''
                SELECT
                    owner_token,
                    acquired_at,
                    heartbeat_at
                FROM research_daemon_lock
                WHERE singleton_id = 1;
                '''
            ).fetchone()
        )

        session_date = (
            latest_run["us_session_date"]
            if latest_run
            else None
        )

        session_summary = {
            "session_date": session_date,
            "runs": 0,
            "completed_runs": 0,
            "failed_runs": 0,
            "attempted_underlyings": 0,
            "succeeded_underlyings": 0,
            "failed_underlyings": 0,
        }

        if session_date:
            row = conn.execute(
                '''
                SELECT
                    COUNT(*) AS runs,
                    SUM(
                        CASE
                            WHEN status = 'COMPLETED'
                            THEN 1 ELSE 0
                        END
                    ) AS completed_runs,
                    SUM(
                        CASE
                            WHEN status = 'FAILED'
                            THEN 1 ELSE 0
                        END
                    ) AS failed_runs,
                    SUM(attempted_underlyings)
                        AS attempted_underlyings,
                    SUM(succeeded_underlyings)
                        AS succeeded_underlyings,
                    SUM(failed_underlyings)
                        AS failed_underlyings
                FROM research_runs
                WHERE us_session_date = ?;
                ''',
                (session_date,),
            ).fetchone()

            if row:
                session_summary = {
                    "session_date":
                        session_date,
                    "runs":
                        int(row["runs"] or 0),
                    "completed_runs":
                        int(row["completed_runs"] or 0),
                    "failed_runs":
                        int(row["failed_runs"] or 0),
                    "attempted_underlyings":
                        int(
                            row["attempted_underlyings"]
                            or 0
                        ),
                    "succeeded_underlyings":
                        int(
                            row["succeeded_underlyings"]
                            or 0
                        ),
                    "failed_underlyings":
                        int(
                            row["failed_underlyings"]
                            or 0
                        ),
                }

        prospective_row = conn.execute(
            '''
            SELECT
                COUNT(*) AS observation_rows,
                COUNT(
                    DISTINCT us_session_date
                ) AS independent_dates,
                SUM(
                    CASE
                        WHEN was_recovered = 1
                        THEN 1 ELSE 0
                    END
                ) AS recovered_rows,
                COUNT(
                    DISTINCT CASE
                        WHEN was_recovered = 1
                        THEN
                            CAST(research_run_id AS TEXT)
                            || ':'
                            || underlying
                    END
                ) AS recovered_samples,
                MIN(
                    prospective_start_session_date
                ) AS prospective_start_session_date
            FROM
                v_local_surface_v2_prospective_partition_v2
            WHERE
                evidence_phase =
                'POST_FREEZE_PROSPECTIVE';
            '''
        ).fetchone()

        prospective = {
            "observation_rows":
                int(
                    prospective_row[
                        "observation_rows"
                    ] or 0
                ),
            "independent_dates":
                int(
                    prospective_row[
                        "independent_dates"
                    ] or 0
                ),
            "recovered_rows":
                int(
                    prospective_row[
                        "recovered_rows"
                    ] or 0
                ),
            "recovered_samples":
                int(
                    prospective_row[
                        "recovered_samples"
                    ] or 0
                ),
            "prospective_start_session_date":
                prospective_row[
                    "prospective_start_session_date"
                ],
        }

        counts_row = conn.execute(
            '''
            SELECT
                (
                    SELECT COUNT(*)
                    FROM hypothesis_scanner_evaluations
                    WHERE evaluation_state = 'SURFACED'
                ) AS surfaced_total,
                (
                    SELECT COUNT(*)
                    FROM shadow_structure_proposals
                    WHERE proposal_state = 'PROPOSED'
                ) AS proposals_total,
                (
                    SELECT COUNT(*)
                    FROM shadow_structure_proposals
                    WHERE proposal_state = 'BLOCKED'
                ) AS proposals_blocked,
                (
                    SELECT COUNT(*)
                    FROM shadow_admission_decisions
                    WHERE decision = 'ADMITTED'
                ) AS admitted_total,
                (
                    SELECT COUNT(*)
                    FROM shadow_admission_decisions
                    WHERE decision = 'BLOCKED'
                ) AS admission_blocked,
                (
                    SELECT COUNT(*)
                    FROM shadow_candidates
                ) AS shadow_candidates,
                (
                    SELECT COUNT(*)
                    FROM shadow_mark_observations
                ) AS shadow_marks;
            '''
        ).fetchone()

        research_counts = {
            key: int(
                counts_row[key] or 0
            )
            for key in counts_row.keys()
        }

        models = _rows_to_dicts(
            conn.execute(
                '''
                SELECT
                    model_key,
                    model_version,
                    model_family,
                    governance_role,
                    evidence_use_enabled,
                    admission_enabled,
                    decision_enabled,
                    notes
                FROM research_model_registry_v1
                ORDER BY id;
                '''
            ).fetchall()
        )

        hypotheses = _rows_to_dicts(
            conn.execute(
                '''
                SELECT
                    h.hypothesis_key,
                    h.description,
                    h.primary_unit,
                    h.primary_metric,
                    h.minimum_independent_dates,
                    h.hypothesis_state,
                    h.decision_enabled
                FROM
                    prospective_research_hypotheses_v1
                    AS h
                JOIN (
                    SELECT MAX(id) AS freeze_run_id
                    FROM
                        prospective_research_freeze_v1_runs
                ) AS latest
                  ON latest.freeze_run_id =
                     h.freeze_run_id
                ORDER BY h.id;
                '''
            ).fetchall()
        )

        theta_timestamp_semantics = _row_to_dict(
            conn.execute(
                """
                SELECT
                    id,
                    semantics_version,
                    validated_at,
                    live_probe_state,
                    confidence_state,
                    decision_enabled
                FROM thetadata_timestamp_semantics_v1_runs
                ORDER BY id DESC
                LIMIT 1;
                """
            ).fetchone()
        )

        recent_iterations = _rows_to_dicts(
            conn.execute(
                '''
                SELECT
                    id,
                    scheduled_for,
                    started_at,
                    completed_at,
                    status,
                    research_run_id,
                    proposals_count,
                    admitted_count,
                    blocked_count,
                    outcome_mark_count,
                    error_type
                FROM research_daemon_iterations
                ORDER BY id DESC
                LIMIT 25;
                '''
            ).fetchall()
        )

        recent_anomalies = _rows_to_dicts(
            conn.execute(
                '''
                SELECT
                    e.id,
                    r.us_session_date,
                    e.underlying,
                    e.expiration,
                    e.strike,
                    e.right,
                    e.iv_residual,
                    e.abs_iv_residual,
                    e.surfaced_direction,
                    s.scanner_version
                FROM
                    hypothesis_scanner_evaluations AS e
                JOIN
                    hypothesis_scanner_runs AS s
                  ON s.id = e.scanner_run_id
                JOIN
                    research_runs AS r
                  ON r.id = s.research_run_id
                WHERE
                    e.evaluation_state = 'SURFACED'
                ORDER BY e.id DESC
                LIMIT 50;
                '''
            ).fetchall()
        )

        recent_proposals = _rows_to_dicts(
            conn.execute(
                '''
                SELECT
                    id,
                    research_run_id,
                    underlying,
                    expiration,
                    right,
                    target_strike,
                    anomaly_direction,
                    proposal_state,
                    reason_code,
                    structure_id,
                    max_theoretical_loss_minor,
                    risk_currency,
                    created_at
                FROM shadow_structure_proposals
                ORDER BY id DESC
                LIMIT 50;
                '''
            ).fetchall()
        )

        recent_candidates = _rows_to_dicts(
            conn.execute(
                '''
                SELECT
                    id,
                    research_run_id,
                    underlying,
                    surfaced_at,
                    universe_status,
                    structure_id,
                    structure_version,
                    max_theoretical_loss_minor,
                    admission_label
                FROM shadow_candidates
                ORDER BY id DESC
                LIMIT 50;
                '''
            ).fetchall()
        )

        recovery_summary = _rows_to_dicts(
            conn.execute(
                '''
                SELECT
                    recovery_error_type,
                    COUNT(*) AS recovered_samples
                FROM research_run_underlyings
                WHERE retry_count > 0
                GROUP BY recovery_error_type
                ORDER BY recovered_samples DESC;
                '''
            ).fetchall()
        )

    finally:
        conn.close()

    daemon_health = assess_daemon_health(
        daemon_lock,
        now=now,
    ).as_dict()

    return {
        "ready": True,
        "reason": None,
        "database": health.as_dict(),
        "market_clock": market_clock,
        "daemon_health": daemon_health,
        "theta_health": theta_health,
        "theta_timestamp_semantics": theta_timestamp_semantics,
        "daemon_lock": daemon_lock,
        "latest_iteration": latest_iteration,
        "latest_run": latest_run,
        "session": session_summary,
        "prospective": prospective,
        "research_counts": research_counts,
        "models": models,
        "hypotheses": hypotheses,
        "recent_iterations": recent_iterations,
        "recent_anomalies": recent_anomalies,
        "recent_proposals": recent_proposals,
        "recent_candidates": recent_candidates,
        "recovery_summary": recovery_summary,
    }
