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

        decision_desk_candidates = _rows_to_dicts(
            conn.execute(
                '''
                SELECT
                    sc.id AS candidate_id,
                    sc.research_run_id,
                    sc.reference_contract_id,
                    sc.underlying,
                    sc.surfaced_at,
                    sc.scanner_family_id,
                    sc.scanner_version,
                    sc.hypothesis_family,
                    sc.hypothesis_version,
                    sc.structure_id,
                    sc.structure_version,
                    sc.admission_label,
                    sc.universe_status,
                    lrc.exercise_style,
                    lrc.primary_exchange,
                    lrc.shares_per_contract AS target_shares_per_contract,
                    ssp.expiration,
                    ssp.right,
                    ssp.target_strike,
                    ssp.anomaly_direction,
                    ssp.structure_json,
                    ssp.entry_pricing_json,
                    ssp.risk_currency,
                    ssp.max_theoretical_loss_minor,
                    ssp.risk_basis,
                    sad.decision AS admission_decision,
                    sad.reason_code AS admission_reason_code,
                    sad.estimated_cost_eur_minor,
                    sad.reserved_risk_eur_minor,
                    sad.bankroll_cap_eur_minor,
                    hse.iv_residual,
                    hse.abs_iv_residual,
                    hse.residual_threshold,
                    hse.surfaced_direction,
                    oq.bid AS target_bid,
                    oq.ask AS target_ask,
                    oq.implied_volatility AS target_implied_volatility,
                    oq.delta AS target_delta,
                    oq.gamma AS target_gamma,
                    oq.theta AS target_theta,
                    oq.vega AS target_vega,
                    oq.quote_at AS target_quote_at,
                    ms.underlying_price,
                    COALESCE(mc.mark_count, 0) AS mark_count,
                    COALESCE(mc.validated_outcomes, 0) AS validated_outcomes,
                    rm.observed_at AS latest_mark_at,
                    rm.estimated_net_pnl_eur_minor
                        AS latest_estimated_net_pnl_eur_minor
                FROM shadow_candidates AS sc
                LEFT JOIN shadow_admission_decisions AS sad
                  ON sad.candidate_id = sc.id
                 AND sad.decision = 'ADMITTED'
                LEFT JOIN shadow_structure_proposals AS ssp
                  ON ssp.id = sad.proposal_id
                LEFT JOIN hypothesis_scanner_evaluations AS hse
                  ON hse.id = ssp.hypothesis_evaluation_id
                LEFT JOIN option_quotes AS oq
                  ON oq.id = hse.option_quote_id
                LEFT JOIN market_snapshots AS ms
                  ON ms.id = oq.snapshot_id
                LEFT JOIN listing_reference_contracts AS lrc
                  ON lrc.id = sc.reference_contract_id
                LEFT JOIN (
                    SELECT
                        candidate_id,
                        COUNT(*) AS mark_count,
                        SUM(CASE WHEN outcome_eligible = 1 THEN 1 ELSE 0 END)
                            AS validated_outcomes
                    FROM shadow_mark_observations
                    GROUP BY candidate_id
                ) AS mc
                  ON mc.candidate_id = sc.id
                LEFT JOIN (
                    SELECT candidate_id, observed_at, estimated_net_pnl_eur_minor
                    FROM (
                        SELECT
                            candidate_id,
                            observed_at,
                            estimated_net_pnl_eur_minor,
                            ROW_NUMBER() OVER (
                                PARTITION BY candidate_id
                                ORDER BY observed_at DESC, id DESC
                            ) AS row_rank
                        FROM shadow_mark_observations
                    )
                    WHERE row_rank = 1
                ) AS rm
                  ON rm.candidate_id = sc.id
                ORDER BY sc.id DESC
                LIMIT 100;
                '''
            ).fetchall()
        )

        leg_quote_ids: set[int] = set()
        for candidate in decision_desk_candidates:
            candidate["structure_legs"] = []
            candidate["model_input_complete"] = False
            try:
                import json
                structure = json.loads(candidate.get("structure_json") or "{}")
                pricing = json.loads(candidate.get("entry_pricing_json") or "{}")
            except (TypeError, ValueError):
                continue

            price_by_quote = {
                int(item["option_quote_id"]): item.get("entry_price")
                for item in pricing.get("legs", [])
                if item.get("option_quote_id") is not None
            }
            legs = []
            for item in structure.get("legs", []):
                quote_id = item.get("option_quote_id")
                if quote_id is None:
                    continue
                quote_id = int(quote_id)
                leg_quote_ids.add(quote_id)
                legs.append(
                    {
                        **item,
                        "option_quote_id": quote_id,
                        "entry_price": price_by_quote.get(quote_id),
                    }
                )
            candidate["structure_legs"] = legs

        leg_quote_map: dict[int, dict[str, Any]] = {}
        if leg_quote_ids:
            placeholders = ",".join("?" for _ in leg_quote_ids)
            leg_rows = conn.execute(
                f"""
                SELECT
                    oq.id AS option_quote_id,
                    oq.strike,
                    oq.right,
                    oq.bid,
                    oq.ask,
                    oq.implied_volatility,
                    oq.delta,
                    oq.gamma,
                    oq.theta,
                    oq.vega,
                    oq.quote_at,
                    oq.shares_per_contract,
                    (
                        SELECT pmo.implied_volatility
                        FROM provider_model_observations AS pmo
                        WHERE pmo.option_quote_id = oq.id
                          AND pmo.implied_volatility IS NOT NULL
                        ORDER BY pmo.id DESC
                        LIMIT 1
                    ) AS provider_implied_volatility,
                    (
                        SELECT pmo.model_underlying_price
                        FROM provider_model_observations AS pmo
                        WHERE pmo.option_quote_id = oq.id
                          AND pmo.model_underlying_price IS NOT NULL
                        ORDER BY pmo.id DESC
                        LIMIT 1
                    ) AS model_underlying_price,
                    (
                        SELECT pmo.model_rate
                        FROM provider_model_observations AS pmo
                        WHERE pmo.option_quote_id = oq.id
                          AND pmo.model_rate IS NOT NULL
                        ORDER BY pmo.id DESC
                        LIMIT 1
                    ) AS model_rate,
                    (
                        SELECT pmo.model_dividend_yield
                        FROM provider_model_observations AS pmo
                        WHERE pmo.option_quote_id = oq.id
                          AND pmo.model_dividend_yield IS NOT NULL
                        ORDER BY pmo.id DESC
                        LIMIT 1
                    ) AS model_dividend_yield
                FROM option_quotes AS oq
                WHERE oq.id IN ({placeholders});
                """,
                tuple(sorted(leg_quote_ids)),
            ).fetchall()
            leg_quote_map = {
                int(row["option_quote_id"]): dict(row)
                for row in leg_rows
            }

        for candidate in decision_desk_candidates:
            enriched_legs = []
            for leg in candidate.get("structure_legs", []):
                quote = leg_quote_map.get(int(leg["option_quote_id"]), {})
                enriched_legs.append({**leg, **quote})
            candidate["structure_legs"] = enriched_legs
            required = (
                candidate.get("underlying_price") is not None
                and candidate.get("expiration") is not None
                and bool(enriched_legs)
                and all(
                    (leg.get("implied_volatility") is not None
                     or leg.get("provider_implied_volatility") is not None)
                    and leg.get("model_rate") is not None
                    and leg.get("model_dividend_yield") is not None
                    and leg.get("entry_price") is not None
                    for leg in enriched_legs
                )
            )
            candidate["model_input_complete"] = bool(required)

        shadow_mark_history = _rows_to_dicts(
            conn.execute(
                '''
                SELECT
                    smo.id,
                    smo.candidate_id,
                    sc.underlying,
                    sc.surfaced_at,
                    smo.observed_at,
                    smo.research_run_id,
                    smo.provider,
                    smo.structure_mark_usd_minor,
                    smo.gross_pnl_usd_minor,
                    smo.estimated_net_pnl_usd_minor,
                    smo.gross_pnl_eur_minor,
                    smo.estimated_net_pnl_eur_minor,
                    smo.quality_state,
                    smo.measurement_role,
                    smo.outcome_eligible
                FROM shadow_mark_observations AS smo
                JOIN shadow_candidates AS sc
                  ON sc.id = smo.candidate_id
                ORDER BY smo.observed_at DESC, smo.id DESC
                LIMIT 250;
                '''
            ).fetchall()
        )

        shadow_candidate_followup = _rows_to_dicts(
            conn.execute(
                '''
                WITH ranked_marks AS (
                    SELECT
                        smo.*,
                        ROW_NUMBER() OVER (
                            PARTITION BY smo.candidate_id
                            ORDER BY smo.observed_at DESC, smo.id DESC
                        ) AS mark_rank
                    FROM shadow_mark_observations AS smo
                ),
                mark_counts AS (
                    SELECT
                        candidate_id,
                        COUNT(*) AS mark_count,
                        SUM(CASE WHEN outcome_eligible = 1 THEN 1 ELSE 0 END)
                            AS validated_outcomes
                    FROM shadow_mark_observations
                    GROUP BY candidate_id
                )
                , latest_state AS (
                    SELECT
                        se.*,
                        ROW_NUMBER() OVER (
                            PARTITION BY se.candidate_id
                            ORDER BY se.id DESC
                        ) AS state_rank
                    FROM shadow_state_events AS se
                ), validated_mark AS (
                    SELECT
                        smo.*,
                        ROW_NUMBER() OVER (
                            PARTITION BY smo.candidate_id
                            ORDER BY smo.observed_at DESC, smo.id DESC
                        ) AS validated_rank
                    FROM shadow_mark_observations AS smo
                    WHERE smo.outcome_eligible = 1
                )
                SELECT
                    sc.id AS candidate_id,
                    sc.underlying,
                    sc.surfaced_at,
                    sc.scanner_family_id,
                    sc.scanner_version,
                    sc.hypothesis_family,
                    sc.hypothesis_version,
                    sc.structure_id,
                    sc.admission_label,
                    ssp.anomaly_direction,
                    COALESCE(mc.mark_count, 0) AS mark_count,
                    rm.observed_at AS latest_mark_at,
                    rm.estimated_net_pnl_eur_minor
                        AS latest_estimated_net_pnl_eur_minor,
                    rm.quality_state AS latest_quality_state,
                    rm.measurement_role AS latest_measurement_role,
                    rm.outcome_eligible AS latest_outcome_eligible,
                    COALESCE(mc.validated_outcomes, 0) AS validated_outcomes,
                    ls.to_state AS current_state,
                    ls.reason_code AS latest_state_reason_code,
                    ls.note AS latest_state_note,
                    vm.estimated_net_pnl_eur_minor AS validated_net_pnl_eur_minor,
                    CASE
                        WHEN ls.to_state = 'SCORED'
                            THEN 'SCORED — REVIEW RECORDED EVIDENCE'
                        ELSE 'NOT YET SCORED'
                    END AS thesis_assessment,
                    CASE
                        WHEN vm.id IS NULL THEN 'NOT YET VALIDATED'
                        WHEN vm.estimated_net_pnl_eur_minor > 0 THEN 'PROFITABLE'
                        WHEN vm.estimated_net_pnl_eur_minor < 0 THEN 'UNPROFITABLE'
                        ELSE 'FLAT'
                    END AS validated_trade_result
                FROM shadow_candidates AS sc
                LEFT JOIN shadow_admission_decisions AS sad
                  ON sad.candidate_id = sc.id
                 AND sad.decision = 'ADMITTED'
                LEFT JOIN shadow_structure_proposals AS ssp
                  ON ssp.id = sad.proposal_id
                LEFT JOIN mark_counts AS mc
                  ON mc.candidate_id = sc.id
                LEFT JOIN ranked_marks AS rm
                  ON rm.candidate_id = sc.id
                 AND rm.mark_rank = 1
                LEFT JOIN latest_state AS ls
                  ON ls.candidate_id = sc.id
                 AND ls.state_rank = 1
                LEFT JOIN validated_mark AS vm
                  ON vm.candidate_id = sc.id
                 AND vm.validated_rank = 1
                ORDER BY sc.id DESC
                LIMIT 100;
                '''
            ).fetchall()
        )

        shadow_tracking_row = conn.execute(
            '''
            SELECT
                COUNT(*) AS mark_observations,
                COUNT(DISTINCT candidate_id) AS marked_candidates,
                SUM(CASE WHEN outcome_eligible = 1 THEN 1 ELSE 0 END)
                    AS validated_outcomes
            FROM shadow_mark_observations;
            '''
        ).fetchone()

        shadow_tracking = {
            "mark_observations": int(
                shadow_tracking_row["mark_observations"] or 0
            ),
            "marked_candidates": int(
                shadow_tracking_row["marked_candidates"] or 0
            ),
            "validated_outcomes": int(
                shadow_tracking_row["validated_outcomes"] or 0
            ),
        }

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

        failed_underlyings = _rows_to_dicts(
            conn.execute(
                '''
                SELECT
                    ru.id,
                    ru.run_id,
                    r.us_session_date,
                    ru.underlying,
                    ru.status,
                    ru.retry_count,
                    ru.failure_code,
                    ru.failure_reason,
                    ru.recovery_error_type,
                    ru.recovery_error_message,
                    ru.attempted_at,
                    ru.completed_at
                FROM research_run_underlyings AS ru
                JOIN research_runs AS r
                  ON r.id = ru.run_id
                WHERE ru.status = 'FAILED'
                ORDER BY ru.id DESC
                LIMIT 50;
                '''
            ).fetchall()
        )

        iteration_quality = _row_to_dict(
            conn.execute(
                '''
                SELECT
                    COUNT(*) AS iterations,
                    SUM(CASE WHEN status = 'COMPLETED' THEN 1 ELSE 0 END) AS completed,
                    SUM(CASE WHEN status = 'FAILED' THEN 1 ELSE 0 END) AS failed,
                    SUM(CASE WHEN status = 'ORPHANED' THEN 1 ELSE 0 END) AS orphaned,
                    SUM(CASE WHEN status = 'RUNNING' THEN 1 ELSE 0 END) AS running
                FROM (
                    SELECT status
                    FROM research_daemon_iterations
                    ORDER BY id DESC
                    LIMIT 100
                );
                '''
            ).fetchone()
        ) or {}

        underlying_quality = _row_to_dict(
            conn.execute(
                '''
                SELECT
                    COUNT(*) AS samples,
                    SUM(CASE WHEN status = 'SUCCESS' THEN 1 ELSE 0 END) AS succeeded,
                    SUM(CASE WHEN status = 'FAILED' THEN 1 ELSE 0 END) AS failed,
                    SUM(CASE WHEN retry_count > 0 THEN 1 ELSE 0 END) AS retried,
                    SUM(CASE WHEN retry_count > 0 AND status = 'SUCCESS' THEN 1 ELSE 0 END) AS recovered
                FROM research_run_underlyings;
                '''
            ).fetchone()
        ) or {}

        failure_types = _rows_to_dicts(
            conn.execute(
                '''
                SELECT
                    COALESCE(failure_code, recovery_error_type, 'UNCLASSIFIED') AS failure_type,
                    COUNT(*) AS samples
                FROM research_run_underlyings
                WHERE status = 'FAILED' OR retry_count > 0
                GROUP BY COALESCE(failure_code, recovery_error_type, 'UNCLASSIFIED')
                ORDER BY samples DESC, failure_type;
                '''
            ).fetchall()
        )

        admission_reason_summary = _rows_to_dicts(
            conn.execute(
                '''
                SELECT
                    decision,
                    reason_code,
                    COUNT(*) AS decisions
                FROM shadow_admission_decisions
                GROUP BY decision, reason_code
                ORDER BY decisions DESC, decision, reason_code;
                '''
            ).fetchall()
        )

        data_quality = {
            "iteration_window": {
                key: int(iteration_quality.get(key) or 0)
                for key in ("iterations", "completed", "failed", "orphaned", "running")
            },
            "underlying_totals": {
                key: int(underlying_quality.get(key) or 0)
                for key in ("samples", "succeeded", "failed", "retried", "recovered")
            },
            "failure_types": failure_types,
            "recent_failed_underlyings": failed_underlyings,
            "admission_reason_summary": admission_reason_summary,
        }

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
        "decision_desk_candidates": decision_desk_candidates,
        "shadow_mark_history": shadow_mark_history,
        "shadow_candidate_followup": shadow_candidate_followup,
        "shadow_tracking": shadow_tracking,
        "recovery_summary": recovery_summary,
        "data_quality": data_quality,
    }
