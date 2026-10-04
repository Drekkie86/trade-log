from __future__ import annotations

import json
import threading
import time
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
from src.dashboard.research_evidence import (
    assess_replay_liquidation_stress,
)


def _row_to_dict(row) -> dict[str, Any] | None:
    if row is None:
        return None
    return dict(row)


def _rows_to_dicts(rows) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


def _decode_json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value or "{}"))
    except (json.JSONDecodeError, TypeError, ValueError):
        return {"state": "INVALID_METRICS_JSON"}
    return parsed if isinstance(parsed, dict) else {"state": "INVALID_METRICS_JSON"}


# ---------------------------------------------------------------------------
# Incremental prospective-evidence summary
#
# The Dashboard/Calibration "prospective" counters were previously computed by
# aggregating the entire v_local_surface_v2_prospective_partition_v2 view on
# every read: O(all V2 observations ever recorded), growing every trading day.
#
# Prospective evidence is append-only (immutability triggers, migration 028),
# and a research run's recovery provenance is final once the run is terminal.
# Aggregates for terminal runs are therefore accumulated once per process and
# each refresh scans only runs newer than a watermark. The original view stays
# the single definition of which rows count; the range predicate on
# research_run_id is pushed down to an index seek.
#
# Correctness guards (any failure forces a full recompute, never a stale value):
#   * cache key includes the latest freeze run id and frozen_through date;
#   * the watermark only advances over runs that are all terminal;
#   * new V2 observation or THETADATA provider rows attached to an already
#     cached run (backfill, late fan-out row) invalidate the cache.
# ---------------------------------------------------------------------------

_TERMINAL_RUN_STATES = ("COMPLETED", "FAILED", "INVALID")
_prospective_cache: dict[tuple, dict[str, Any]] = {}
_prospective_cache_lock = threading.Lock()


def _empty_prospective_part() -> dict[str, Any]:
    return {
        "observation_rows": 0,
        "dates": set(),
        "recovered_rows": 0,
        "recovered_samples": 0,
        "prospective_start_session_date": None,
    }


def _prospective_range_part(
    conn,
    *,
    low_exclusive: int | None = None,
    high_inclusive: int | None = None,
    include_ids: frozenset[int] | None = None,
    exclude_ids: frozenset[int] = frozenset(),
) -> dict[str, Any]:
    if include_ids is not None and not include_ids:
        return _empty_prospective_part()
    clauses = ["evidence_phase = 'POST_FREEZE_PROSPECTIVE'"]
    params: list[Any] = []
    if low_exclusive is not None:
        clauses.append("research_run_id > ?")
        params.append(low_exclusive)
    if high_inclusive is not None:
        clauses.append("research_run_id <= ?")
        params.append(high_inclusive)
    if include_ids is not None:
        clauses.append(f"research_run_id IN ({','.join('?' for _ in include_ids)})")
        params.extend(sorted(include_ids))
    if exclude_ids:
        clauses.append(f"research_run_id NOT IN ({','.join('?' for _ in exclude_ids)})")
        params.extend(sorted(exclude_ids))
    where = " AND ".join(clauses)
    rows = conn.execute(
        f'''
        WITH prospective_rows AS (
            SELECT
                us_session_date,
                was_recovered,
                research_run_id,
                underlying,
                prospective_start_session_date
            FROM v_local_surface_v2_prospective_partition_v2
            WHERE {where}
        )
        SELECT
            us_session_date,
            COUNT(*) AS observation_rows,
            SUM(CASE WHEN was_recovered = 1 THEN 1 ELSE 0 END) AS recovered_rows,
            MIN(prospective_start_session_date) AS prospective_start_session_date
        FROM prospective_rows
        GROUP BY us_session_date;
        ''',
        params,
    ).fetchall()
    pairs = conn.execute(
        f'''
        SELECT COUNT(*) FROM (
            SELECT research_run_id, underlying
            FROM v_local_surface_v2_prospective_partition_v2
            WHERE {where} AND was_recovered = 1
            GROUP BY research_run_id, underlying
        );
        ''',
        params,
    ).fetchone()[0]
    part = _empty_prospective_part()
    for row in rows:
        part["observation_rows"] += int(row["observation_rows"] or 0)
        part["recovered_rows"] += int(row["recovered_rows"] or 0)
        if row["us_session_date"] is not None:
            part["dates"].add(row["us_session_date"])
        start = row["prospective_start_session_date"]
        if start is not None and (
            part["prospective_start_session_date"] is None
            or start < part["prospective_start_session_date"]
        ):
            part["prospective_start_session_date"] = start
    part["recovered_samples"] = int(pairs or 0)
    return part


def _merge_prospective(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    starts = [
        x for x in (a["prospective_start_session_date"], b["prospective_start_session_date"])
        if x is not None
    ]
    return {
        "observation_rows": a["observation_rows"] + b["observation_rows"],
        "dates": a["dates"] | b["dates"],
        "recovered_rows": a["recovered_rows"] + b["recovered_rows"],
        "recovered_samples": a["recovered_samples"] + b["recovered_samples"],
        "prospective_start_session_date": min(starts) if starts else None,
    }


def _max_id(conn, table: str) -> int:
    value = conn.execute(f"SELECT MAX(id) FROM {table};").fetchone()[0]
    return int(value or 0)


def _late_evidence_for_cached_runs(conn, state: dict[str, Any]) -> bool:
    """True if evidence was attached to a run already folded into the cache."""
    cached_high = state["max_seen_run_id"]
    open_ids = state["open_run_ids"]
    exclusion = ""
    params: list[Any] = [state["max_observation_id"], cached_high]
    if open_ids:
        exclusion = f" AND r.research_run_id NOT IN ({','.join('?' for _ in open_ids)})"
        params.extend(sorted(open_ids))
    late_observation = conn.execute(
        f'''
        SELECT 1
        FROM local_surface_residual_v2_observations AS o
        -- CROSS JOIN pins the join order: the rowid range over rows newer than
        -- the last refresh is the outer loop, so this check is O(new rows).
        CROSS JOIN local_surface_residual_v2_runs AS r ON r.id = o.model_run_id
        WHERE o.id > ? AND r.research_run_id <= ?{exclusion}
        LIMIT 1;
        ''',
        params,
    ).fetchone()
    if late_observation is not None:
        return True
    params[0] = state["max_provider_id"]
    late_provider_row = conn.execute(
        f'''
        SELECT 1
        FROM provider_model_observations AS pmo
        -- CROSS JOIN pins pmo's rowid range (new rows only) as the outer loop.
        CROSS JOIN local_surface_residual_v2_observations AS o ON o.option_quote_id = pmo.option_quote_id
        CROSS JOIN local_surface_residual_v2_runs AS r ON r.id = o.model_run_id
        WHERE pmo.id > ? AND r.research_run_id <= ?{exclusion}
          AND pmo.provider = 'THETADATA'
        LIMIT 1;
        ''',
        params,
    ).fetchone()
    return late_provider_row is not None


def _open_run_ids(conn) -> frozenset[int]:
    placeholders = ",".join("?" for _ in _TERMINAL_RUN_STATES)
    rows = conn.execute(
        f'''
        SELECT id FROM research_runs
        WHERE status IS NULL OR status NOT IN ({placeholders});
        ''',
        _TERMINAL_RUN_STATES,
    ).fetchall()
    return frozenset(int(row[0]) for row in rows)


def _load_prospective_summary(conn, path: Path) -> dict[str, Any]:
    # One read transaction: every statement below sees the same snapshot, so a
    # run created or closed mid-refresh cannot be miscounted or cached open.
    owns_transaction = not conn.in_transaction
    if owns_transaction:
        conn.execute("BEGIN;")
    try:
        return _load_prospective_summary_in_snapshot(conn, path)
    finally:
        if owns_transaction:
            conn.execute("COMMIT;")


def _load_prospective_summary_in_snapshot(conn, path: Path) -> dict[str, Any]:
    freeze = conn.execute(
        '''
        SELECT id, frozen_through_session_date
        FROM prospective_research_freeze_v1_runs
        ORDER BY id DESC
        LIMIT 1;
        '''
    ).fetchone()
    if freeze is None:
        part = _empty_prospective_part()
    else:
        key = (str(Path(path).resolve()), int(freeze["id"]), freeze["frozen_through_session_date"])
        open_now = _open_run_ids(conn)
        with _prospective_cache_lock:
            state = _prospective_cache.get(key)
            if state is not None:
                reopened = {
                    run_id for run_id in open_now
                    if run_id <= state["max_seen_run_id"]
                    and run_id not in state["open_run_ids"]
                }
                if reopened or _late_evidence_for_cached_runs(conn, state):
                    state = None
            max_observation_id = _max_id(conn, "local_surface_residual_v2_observations")
            max_provider_id = _max_id(conn, "provider_model_observations")
            max_run_id = _max_id(conn, "research_runs")
            if state is None:
                state = {
                    "max_seen_run_id": 0,
                    "open_run_ids": frozenset(),
                    "part": _empty_prospective_part(),
                }
            # Runs that were open at the last refresh and are terminal now.
            newly_closed = state["open_run_ids"] - open_now
            part_acc = state["part"]
            if newly_closed:
                part_acc = _merge_prospective(
                    part_acc,
                    _prospective_range_part(conn, include_ids=frozenset(newly_closed)),
                )
            # Runs created since the last refresh that are already terminal.
            if max_run_id > state["max_seen_run_id"]:
                part_acc = _merge_prospective(
                    part_acc,
                    _prospective_range_part(
                        conn,
                        low_exclusive=state["max_seen_run_id"],
                        high_inclusive=max_run_id,
                        exclude_ids=frozenset(
                            run_id for run_id in open_now
                            if run_id > state["max_seen_run_id"]
                        ),
                    ),
                )
            state = {
                "max_seen_run_id": max(max_run_id, state["max_seen_run_id"]),
                "open_run_ids": frozenset(
                    run_id for run_id in open_now
                    if run_id <= max(max_run_id, state["max_seen_run_id"])
                ),
                "part": part_acc,
                "max_observation_id": max_observation_id,
                "max_provider_id": max_provider_id,
            }
            _prospective_cache[key] = state
            cached = state["part"]
        # Non-terminal runs are never cached; they are recomputed live.
        part = _merge_prospective(
            cached,
            _prospective_range_part(conn, include_ids=state["open_run_ids"]),
        )
    return {
        "observation_rows": part["observation_rows"],
        "independent_dates": len(part["dates"]),
        "recovered_rows": part["recovered_rows"],
        "recovered_samples": part["recovered_samples"],
        "prospective_start_session_date": part["prospective_start_session_date"],
    }


def _clear_prospective_summary_cache() -> None:
    with _prospective_cache_lock:
        _prospective_cache.clear()


_PAGE_SECTIONS: dict[str, frozenset[str]] = {
    "Dashboard": frozenset({
        "runtime",
        "prospective",
        "counts",
        "governance",
        "lifecycle",
        "runs",
    }),
    "Decision Desk": frozenset({
        "governance",
        "decision",
    }),
    "Research Runs": frozenset({
        "runtime",
        "runs",
        "data_quality",
    }),
    "Calibration": frozenset({
        "prospective",
        "governance",
        "checkpoint",
    }),
    "Observations": frozenset({
        "observations",
    }),
    "Shadow Lab": frozenset({
        "counts",
        "replay",
        "lifecycle",
        "shadow",
    }),
    "Quant Models": frozenset(),
    "Storm Cellar / 0DTE Lab": frozenset(),
    "Ops": frozenset({
        "runtime",
        "theta_semantics",
        "data_quality",
    }),
    "Ops Readiness": frozenset({
        "runtime",
        "prospective",
        "governance",
        "data_quality",
    }),
}


def _requested_sections(page: str | None) -> frozenset[str] | None:
    if page is None:
        return None
    try:
        return _PAGE_SECTIONS[page]
    except KeyError as exc:
        raise ValueError(f"Unsupported Christiania page: {page}") from exc


def load_command_deck(
    db_path: str | Path | None = None,
    *,
    now: datetime | None = None,
    include_provider_health: bool = False,
    deep_integrity: bool = True,
    page: str | None = None,
) -> dict[str, Any]:
    total_started = time.perf_counter()
    timings: dict[str, float] = {}
    sections = _requested_sections(page)

    def _needs(section: str) -> bool:
        return sections is None or section in sections

    path = resolve_db_path(db_path)
    health_started = time.perf_counter()
    health = inspect_database(
        path,
        deep_integrity=deep_integrity,
    )
    timings["database_health_ms"] = round(
        (time.perf_counter() - health_started) * 1000.0,
        3,
    )
    market_started = time.perf_counter()
    market_clock = market_clock_snapshot(
        now=now
    ).as_dict()
    timings["market_clock_ms"] = round(
        (time.perf_counter() - market_started) * 1000.0,
        3,
    )
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
        deep_integrity
        and (
            health.quick_check != "ok"
            or health.foreign_key_violation_count != 0
        )
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

    latest_run = None
    latest_iteration = None
    daemon_lock = None
    session_summary: dict[str, Any] = {}
    prospective = {
        "observation_rows": 0,
        "independent_dates": 0,
        "recovered_rows": 0,
        "recovered_samples": 0,
        "prospective_start_session_date": None,
    }
    research_counts = {
        "surfaced_total": 0,
        "proposals_total": 0,
        "proposals_blocked": 0,
        "admitted_total": 0,
        "admission_blocked": 0,
        "shadow_candidates": 0,
        "shadow_marks": 0,
    }
    models: list[dict[str, Any]] = []
    hypotheses: list[dict[str, Any]] = []
    checkpoint_evaluations: list[dict[str, Any]] = []
    historical_replay_latest: list[dict[str, Any]] = []
    replay_outcome_recovery: list[dict[str, Any]] = []
    historical_replay_summary: dict[str, Any] = {}
    lifecycle_health: dict[str, Any] = {}
    theta_timestamp_semantics = None
    recent_iterations: list[dict[str, Any]] = []
    universe_coverage: dict[str, Any] = {}
    recent_anomalies: list[dict[str, Any]] = []
    recent_proposals: list[dict[str, Any]] = []
    recent_candidates: list[dict[str, Any]] = []
    decision_desk_candidates: list[dict[str, Any]] = []
    shadow_mark_history: list[dict[str, Any]] = []
    shadow_candidate_followup: list[dict[str, Any]] = []
    shadow_tracking: dict[str, Any] = {}
    recovery_summary: list[dict[str, Any]] = []
    data_quality: dict[str, Any] = {}
    shadow_risk_current: list[dict[str, Any]] = []

    conn = open_readonly_connection(
        path
    )

    try:
        if _needs("runtime"):
            _section_started = time.perf_counter()
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

            timings["runtime_ms"] = round(
                (time.perf_counter() - _section_started) * 1000.0,
                3,
            )

        if _needs("prospective"):
            _section_started = time.perf_counter()
            prospective = _load_prospective_summary(conn, path)

            timings["prospective_ms"] = round(
                (time.perf_counter() - _section_started) * 1000.0,
                3,
            )

        if _needs("counts"):
            _section_started = time.perf_counter()
            counts_row = conn.execute(
                '''
                SELECT
                    (
                        SELECT COALESCE(SUM(surfaced_count), 0)
                        FROM hypothesis_scanner_runs
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
                        FROM v_shadow_admission_decisions_all
                        WHERE decision = 'ADMITTED'
                    ) AS admitted_total,
                    (
                        SELECT COUNT(*)
                        FROM v_shadow_admission_decisions_all
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

            timings["counts_ms"] = round(
                (time.perf_counter() - _section_started) * 1000.0,
                3,
            )

        if _needs("governance"):
            _section_started = time.perf_counter()
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

            timings["governance_ms"] = round(
                (time.perf_counter() - _section_started) * 1000.0,
                3,
            )

        if _needs("checkpoint"):
            _section_started = time.perf_counter()
            checkpoint_evaluations = _rows_to_dicts(
                conn.execute(
                    '''
                    SELECT
                        e.id,
                        e.freeze_run_id,
                        e.hypothesis_id,
                        e.hypothesis_key,
                        h.description,
                        e.evaluation_version,
                        e.evaluated_at,
                        e.evidence_start_session_date,
                        e.evidence_end_session_date,
                        e.independent_date_count,
                        e.observation_count,
                        e.evaluation_state,
                        e.metrics_json,
                        e.p_values_enabled,
                        e.fdr_enabled,
                        e.decision_enabled
                    FROM v_prospective_research_hypothesis_latest_v1 AS e
                    JOIN prospective_research_hypotheses_v1 AS h
                      ON h.id = e.hypothesis_id
                    ORDER BY h.id;
                    '''
                ).fetchall()
            )

            for checkpoint in checkpoint_evaluations:
                checkpoint["metrics"] = _decode_json_object(
                    checkpoint.get("metrics_json")
                )

            timings["checkpoint_ms"] = round(
                (time.perf_counter() - _section_started) * 1000.0,
                3,
            )

        if _needs("replay"):
            _section_started = time.perf_counter()
            replay_latest_rows = _rows_to_dicts(
                conn.execute(
                    '''
                    SELECT
                        hpr.id AS policy_replay_id,
                        hpr.proposal_id,
                        hpr.original_decided_at,
                        hpr.original_reason_code,
                        hpr.counterfactual_decision,
                        hpr.intrinsic_risk_eur_minor,
                        hpr.estimated_cost_usd_minor,
                        hpr.estimated_cost_eur_minor,
                        fx.rate AS entry_eur_to_usd,
                        ssp.underlying,
                        ssp.expiration,
                        ssp.right,
                        ssp.target_strike,
                        ssp.structure_id,
                        ssp.anomaly_direction,
                        ssp.structure_json,
                        lm.id AS mark_id,
                        lm.research_run_id AS mark_research_run_id,
                        lm.observed_at,
                        lm.quality_state,
                        lm.structure_mark_usd_minor,
                        lm.gross_pnl_usd_minor,
                        lm.estimated_net_pnl_usd_minor,
                        lm.gross_pnl_eur_minor,
                        lm.estimated_net_pnl_eur_minor,
                        lm.measurement_role,
                        lm.outcome_eligible,
                        lm.evidence_json
                    FROM historical_policy_replay_v1 AS hpr
                    JOIN shadow_structure_proposals AS ssp
                      ON ssp.id = hpr.proposal_id
                    JOIN fx_observations AS fx
                      ON fx.id = hpr.original_fx_observation_id
                    LEFT JOIN historical_replay_marks_v1 AS lm
                      ON lm.id = (
                          SELECT hrm.id
                          FROM historical_replay_marks_v1 AS hrm
                          WHERE hrm.policy_replay_id = hpr.id
                            AND hrm.quality_state =
                                'COMPLETE_RECONSTRUCTED_CONSERVATIVE_LIQUIDATION'
                          ORDER BY hrm.observed_at DESC, hrm.id DESC
                          LIMIT 1
                      )
                    WHERE hpr.counterfactual_decision = 'WOULD_ADMIT'
                    ORDER BY hpr.id;
                    '''
                ).fetchall()
            )

            historical_replay_latest = [
                assess_replay_liquidation_stress(row)
                for row in replay_latest_rows
            ]

            replay_mark_totals = _row_to_dict(
                conn.execute(
                    '''
                    SELECT
                        COUNT(*) AS mark_count,
                        SUM(
                            CASE
                                WHEN quality_state =
                                    'COMPLETE_RECONSTRUCTED_CONSERVATIVE_LIQUIDATION'
                                THEN 1 ELSE 0
                            END
                        ) AS complete_mark_count,
                        SUM(
                            CASE
                                WHEN quality_state !=
                                    'COMPLETE_RECONSTRUCTED_CONSERVATIVE_LIQUIDATION'
                                THEN 1 ELSE 0
                            END
                        ) AS incomplete_mark_count
                    FROM historical_replay_marks_v1;
                    '''
                ).fetchone()
            ) or {}

            replay_outcome_recovery = _rows_to_dicts(
                conn.execute(
                    '''
                    SELECT
                        source_population,
                        recovery_state,
                        reason_code,
                        COUNT(*) AS count
                    FROM historical_outcome_recovery_v1
                    GROUP BY
                        source_population,
                        recovery_state,
                        reason_code
                    ORDER BY
                        source_population,
                        recovery_state,
                        reason_code;
                    '''
                ).fetchall()
            )

            historical_replay_summary = {
                "would_admit_count": len(replay_latest_rows),
                "with_complete_latest_mark": sum(
                    row.get("mark_id") is not None
                    for row in replay_latest_rows
                ),
                "mark_count": int(
                    replay_mark_totals.get("mark_count") or 0
                ),
                "complete_mark_count": int(
                    replay_mark_totals.get("complete_mark_count") or 0
                ),
                "incomplete_mark_count": int(
                    replay_mark_totals.get("incomplete_mark_count") or 0
                ),
                "midpoint_incoherent_latest": sum(
                    row.get("package_coherence_state")
                    == "MIDPOINT_OUTSIDE_BUTTERFLY_BOUNDS"
                    for row in historical_replay_latest
                ),
                "stress_exceeds_intrinsic_risk_latest": sum(
                    (row.get("stress_loss_to_intrinsic_risk") or 0) > 1
                    for row in historical_replay_latest
                ),
                "economic_pnl_eligible_latest": sum(
                    bool(row.get("economic_pnl_eligible"))
                    for row in historical_replay_latest
                ),
                "interpretation": "LIQUIDATION_STRESS_NOT_ECONOMIC_PNL",
            }

            timings["replay_ms"] = round(
                (time.perf_counter() - _section_started) * 1000.0,
                3,
            )

        if _needs("lifecycle"):
            _section_started = time.perf_counter()
            latest_completed_session_row = conn.execute(
                '''
                SELECT MAX(us_session_date) AS session_date
                FROM research_runs
                WHERE status = 'COMPLETED';
                '''
            ).fetchone()
            latest_completed_session_date = (
                None
                if latest_completed_session_row is None
                else latest_completed_session_row["session_date"]
            )

            stale_lifecycle_candidates = []
            if latest_completed_session_date:
                stale_lifecycle_candidates = _rows_to_dicts(
                    conn.execute(
                        '''
                        WITH latest_state AS (
                            SELECT
                                se.*,
                                ROW_NUMBER() OVER (
                                    PARTITION BY se.candidate_id
                                    ORDER BY se.id DESC
                                ) AS state_rank
                            FROM shadow_state_events AS se
                        )
                        SELECT
                            sc.id AS candidate_id,
                            sc.underlying,
                            lrc.expiration,
                            ls.to_state AS current_state,
                            ls.occurred_at AS state_at,
                            ls.reason_code AS state_reason
                        FROM shadow_candidates AS sc
                        JOIN listing_reference_contracts AS lrc
                          ON lrc.id = sc.reference_contract_id
                        JOIN latest_state AS ls
                          ON ls.candidate_id = sc.id
                         AND ls.state_rank = 1
                        WHERE ls.to_state = 'SHADOW_TRACKED'
                          AND lrc.expiration < ?
                        ORDER BY lrc.expiration, sc.id;
                        ''',
                        (latest_completed_session_date,),
                    ).fetchall()
                )

            lifecycle_health = {
                "state": (
                    "PASS"
                    if not stale_lifecycle_candidates
                    else "WARN"
                ),
                "latest_completed_session_date":
                    latest_completed_session_date,
                "stale_tracked_count": len(
                    stale_lifecycle_candidates
                ),
                "stale_candidates": stale_lifecycle_candidates,
                "rule": (
                    "SHADOW_TRACKED must close only after a completed "
                    "research session whose US session date is later "
                    "than expiration."
                ),
            }

            timings["lifecycle_ms"] = round(
                (time.perf_counter() - _section_started) * 1000.0,
                3,
            )

        if _needs("theta_semantics"):
            _section_started = time.perf_counter()
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

            timings["theta_semantics_ms"] = round(
                (time.perf_counter() - _section_started) * 1000.0,
                3,
            )

        if _needs("runs"):
            _section_started = time.perf_counter()
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
                        error_type,
                        evidence_json
                    FROM research_daemon_iterations
                    ORDER BY id DESC
                    LIMIT 25;
                    '''
                ).fetchall()
            )

            universe_symbols: set[str] = set()
            universe_profile = None
            universe_size = 0
            batch_count = 0
            latest_batch_index = None
            latest_batch_size = 0
            parsed_iteration_evidence: list[dict[str, Any]] = []

            for iteration in recent_iterations:
                raw_evidence = iteration.pop("evidence_json", None)
                if not raw_evidence:
                    continue
                try:
                    evidence = json.loads(raw_evidence)
                except (TypeError, ValueError):
                    continue
                if isinstance(evidence, dict):
                    parsed_iteration_evidence.append(evidence)

            for evidence in parsed_iteration_evidence:
                context = evidence.get("universe")
                if not isinstance(context, dict):
                    continue
                universe_profile = context.get("profile")
                universe_size = int(context.get("universe_size") or 0)
                batch_count = int(context.get("batch_count") or 0)
                latest_batch_index = context.get("batch_index")
                latest_batch_size = int(context.get("batch_size") or 0)
                break

            for evidence in parsed_iteration_evidence:
                context = evidence.get("universe")
                if not isinstance(context, dict):
                    continue
                if context.get("profile") != universe_profile:
                    continue
                if int(context.get("universe_size") or 0) != universe_size:
                    continue

                for symbol in evidence.get("symbols") or []:
                    value = str(symbol).strip().upper()
                    if value:
                        universe_symbols.add(value)

            universe_coverage = {
                "profile": universe_profile,
                "configured_symbols": universe_size,
                "covered_symbols": len(universe_symbols),
                "coverage_pct": (
                    0.0
                    if universe_size <= 0
                    else min(100.0, 100.0 * len(universe_symbols) / universe_size)
                ),
                "batch_count": batch_count,
                "latest_batch_index": latest_batch_index,
                "latest_batch_size": latest_batch_size,
                "recent_window_iterations": len(recent_iterations),
            }

            timings["runs_ms"] = round(
                (time.perf_counter() - _section_started) * 1000.0,
                3,
            )

        if _needs("observations"):
            _section_started = time.perf_counter()
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

            timings["observations_ms"] = round(
                (time.perf_counter() - _section_started) * 1000.0,
                3,
            )

        if _needs("shadow"):
            _section_started = time.perf_counter()
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

            timings["shadow_recent_ms"] = round(
                (time.perf_counter() - _section_started) * 1000.0,
                3,
            )

        if _needs("decision"):
            _section_started = time.perf_counter()
            decision_desk_candidates = _rows_to_dicts(
                conn.execute(
                    '''
                    WITH recent_candidates AS (
                        SELECT *
                        FROM shadow_candidates
                        ORDER BY id DESC
                        LIMIT 100
                    ),
                    mark_counts AS (
                        SELECT
                            smo.candidate_id,
                            COUNT(*) AS mark_count,
                            SUM(CASE WHEN smo.outcome_eligible = 1 THEN 1 ELSE 0 END)
                                AS validated_outcomes
                        FROM shadow_mark_observations AS smo
                        JOIN recent_candidates AS rc
                          ON rc.id = smo.candidate_id
                        GROUP BY smo.candidate_id
                    ),
                    latest_marks AS (
                        SELECT
                            smo.candidate_id,
                            smo.observed_at,
                            smo.estimated_net_pnl_eur_minor,
                            ROW_NUMBER() OVER (
                                PARTITION BY smo.candidate_id
                                ORDER BY smo.observed_at DESC, smo.id DESC
                            ) AS row_rank
                        FROM shadow_mark_observations AS smo
                        JOIN recent_candidates AS rc
                          ON rc.id = smo.candidate_id
                    )
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
                        ru.status AS collection_status,
                        ru.retry_count,
                        CASE WHEN ru.retry_count > 0 AND ru.status = 'SUCCESS' THEN 1 ELSE 0 END AS was_recovered,
                        ru.failure_code AS collection_failure_code,
                        ru.recovery_error_type,
                        COALESCE(mc.mark_count, 0) AS mark_count,
                        COALESCE(mc.validated_outcomes, 0) AS validated_outcomes,
                        rm.observed_at AS latest_mark_at,
                        rm.estimated_net_pnl_eur_minor
                            AS latest_estimated_net_pnl_eur_minor
                    FROM recent_candidates AS sc
                    LEFT JOIN v_shadow_admission_decisions_all AS sad
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
                    LEFT JOIN research_run_underlyings AS ru
                      ON ru.run_id = sc.research_run_id
                     AND ru.underlying = sc.underlying
                    LEFT JOIN mark_counts AS mc
                      ON mc.candidate_id = sc.id
                    LEFT JOIN latest_marks AS rm
                      ON rm.candidate_id = sc.id
                     AND rm.row_rank = 1
                    ORDER BY sc.id DESC;
                    '''
                ).fetchall()
            )

            leg_quote_ids: set[int] = set()
            for candidate in decision_desk_candidates:
                candidate["structure_legs"] = []
                candidate["model_input_complete"] = False
                try:
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

            similar_evidence_rows = _rows_to_dicts(
                conn.execute(
                    """
                    SELECT
                        sc.hypothesis_family,
                        COUNT(DISTINCT sc.id) AS candidate_count,
                        COUNT(DISTINCT r.us_session_date) AS independent_dates,
                        SUM(CASE WHEN smo.outcome_eligible = 1 THEN 1 ELSE 0 END) AS validated_outcomes,
                        SUM(CASE WHEN smo.outcome_eligible = 1 AND smo.estimated_net_pnl_eur_minor > 0 THEN 1 ELSE 0 END) AS profitable_outcomes,
                        SUM(CASE WHEN smo.outcome_eligible = 1 AND smo.estimated_net_pnl_eur_minor < 0 THEN 1 ELSE 0 END) AS unprofitable_outcomes,
                        AVG(CASE WHEN smo.outcome_eligible = 1 THEN smo.estimated_net_pnl_eur_minor END) AS mean_net_pnl_eur_minor
                    FROM shadow_candidates AS sc
                    JOIN research_runs AS r ON r.id = sc.research_run_id
                    LEFT JOIN shadow_mark_observations AS smo ON smo.candidate_id = sc.id
                    WHERE r.us_session_date >= (
                        SELECT prospective_start_session_date
                        FROM prospective_research_freeze_v1_runs
                        ORDER BY id DESC LIMIT 1
                    )
                    GROUP BY sc.hypothesis_family;
                    """
                ).fetchall()
            )
            similar_evidence_map = {
                str(row.get("hypothesis_family") or ""): row
                for row in similar_evidence_rows
            }
            for candidate in decision_desk_candidates:
                evidence = similar_evidence_map.get(str(candidate.get("hypothesis_family") or ""), {})
                candidate["similar_candidate_count"] = int(evidence.get("candidate_count") or 0)
                candidate["similar_independent_dates"] = int(evidence.get("independent_dates") or 0)
                candidate["similar_validated_outcomes"] = int(evidence.get("validated_outcomes") or 0)
                candidate["similar_profitable_outcomes"] = int(evidence.get("profitable_outcomes") or 0)
                candidate["similar_unprofitable_outcomes"] = int(evidence.get("unprofitable_outcomes") or 0)
                candidate["similar_mean_net_pnl_eur_minor"] = evidence.get("mean_net_pnl_eur_minor")

            timings["decision_ms"] = round(
                (time.perf_counter() - _section_started) * 1000.0,
                3,
            )

        if _needs("shadow"):
            _section_started = time.perf_counter()
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
                        CASE
                            WHEN smo.measurement_role =
                                'INDEPENDENT_LEG_LIQUIDATION_STRESS'
                            THEN smo.estimated_net_pnl_eur_minor
                        END AS liquidation_stress_eur_minor,
                        CASE
                            WHEN smo.outcome_eligible = 1
                            THEN smo.estimated_net_pnl_eur_minor
                        END AS validated_net_pnl_eur_minor,
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
                    WITH recent_candidates AS (
                        SELECT *
                        FROM shadow_candidates
                        ORDER BY id DESC
                        LIMIT 100
                    ),
                    ranked_marks AS (
                        SELECT
                            smo.*,
                            ROW_NUMBER() OVER (
                                PARTITION BY smo.candidate_id
                                ORDER BY smo.observed_at DESC, smo.id DESC
                            ) AS mark_rank
                        FROM shadow_mark_observations AS smo
                        JOIN recent_candidates AS rc
                          ON rc.id = smo.candidate_id
                    ),
                    mark_counts AS (
                        SELECT
                            smo.candidate_id,
                            COUNT(*) AS mark_count,
                            SUM(CASE WHEN smo.outcome_eligible = 1 THEN 1 ELSE 0 END)
                                AS validated_outcomes
                        FROM shadow_mark_observations AS smo
                        JOIN recent_candidates AS rc
                          ON rc.id = smo.candidate_id
                        GROUP BY smo.candidate_id
                    ),
                    latest_state AS (
                        SELECT
                            se.*,
                            ROW_NUMBER() OVER (
                                PARTITION BY se.candidate_id
                                ORDER BY se.id DESC
                            ) AS state_rank
                        FROM shadow_state_events AS se
                        JOIN recent_candidates AS rc
                          ON rc.id = se.candidate_id
                    ),
                    validated_mark AS (
                        SELECT
                            smo.*,
                            ROW_NUMBER() OVER (
                                PARTITION BY smo.candidate_id
                                ORDER BY smo.observed_at DESC, smo.id DESC
                            ) AS validated_rank
                        FROM shadow_mark_observations AS smo
                        JOIN recent_candidates AS rc
                          ON rc.id = smo.candidate_id
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
                    FROM recent_candidates AS sc
                    LEFT JOIN v_shadow_admission_decisions_all AS sad
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
                    ORDER BY sc.id DESC;
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

            risk_exit_tracking_row = conn.execute(
                """
                SELECT
                    COUNT(*) AS risk_exit_outcomes,
                    SUM(CASE WHEN evidence_eligible = 1 THEN 1 ELSE 0 END)
                        AS eligible_risk_exit_outcomes
                FROM shadow_risk_exit_outcomes;
                """
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
                "risk_exit_outcomes": int(
                    risk_exit_tracking_row["risk_exit_outcomes"] or 0
                ),
                "eligible_risk_exit_outcomes": int(
                    risk_exit_tracking_row["eligible_risk_exit_outcomes"] or 0
                ),
            }

            timings["shadow_detail_ms"] = round(
                (time.perf_counter() - _section_started) * 1000.0,
                3,
            )

        if _needs("data_quality"):
            _section_started = time.perf_counter()
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
                    FROM v_shadow_admission_decisions_all
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

            timings["data_quality_ms"] = round(
                (time.perf_counter() - _section_started) * 1000.0,
                3,
            )

        if _needs("decision"):
            _section_started = time.perf_counter()
            shadow_risk_current = _rows_to_dicts(
                conn.execute("SELECT * FROM v_shadow_risk_current ORDER BY candidate_id DESC LIMIT 100;").fetchall()
            )
            shadow_risk_map = {int(row["candidate_id"]): row for row in shadow_risk_current}
            for candidate in decision_desk_candidates:
                risk = shadow_risk_map.get(int(candidate.get("candidate_id") or 0))
                candidate["frozen_risk_plan"] = risk
                candidate["frozen_risk_plan_state"] = "FROZEN" if risk else "NOT_FROZEN"
                candidate["latest_risk_assessment_state"] = None if not risk else risk.get("overall_state")

            timings["decision_risk_ms"] = round(
                (time.perf_counter() - _section_started) * 1000.0,
                3,
            )

    finally:
        conn.close()

    daemon_health = (
        assess_daemon_health(
            daemon_lock,
            now=now,
        ).as_dict()
        if _needs("runtime")
        else {
            "state": "NOT_LOADED",
            "detail": "Runtime state not requested for this page.",
        }
    )
    timings["total_ms"] = round(
        (time.perf_counter() - total_started) * 1000.0,
        3,
    )

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
        "checkpoint_evaluations": checkpoint_evaluations,
        "historical_replay_summary": historical_replay_summary,
        "historical_replay_latest": historical_replay_latest,
        "replay_outcome_recovery": replay_outcome_recovery,
        "lifecycle_health": lifecycle_health,
        "recent_iterations": recent_iterations,
        "universe_coverage": universe_coverage,
        "recent_anomalies": recent_anomalies,
        "recent_proposals": recent_proposals,
        "recent_candidates": recent_candidates,
        "decision_desk_candidates": decision_desk_candidates,
        "shadow_mark_history": shadow_mark_history,
        "shadow_candidate_followup": shadow_candidate_followup,
        "shadow_tracking": shadow_tracking,
        "shadow_risk_current": shadow_risk_current,
        "recovery_summary": recovery_summary,
        "data_quality": data_quality,
        "read_model_page": page or "FULL",
        "read_model_timings_ms": timings,
    }
