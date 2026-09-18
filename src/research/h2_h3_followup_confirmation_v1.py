from __future__ import annotations

from array import array
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import hashlib
import json
from typing import Any

import numpy as np

from src.database.repository import get_connection


PROGRAM_KEY = "H2_H3_FOLLOWUP_CONFIRMATION_V1"
PROTOCOL_VERSION = "1.0.0"
EVALUATION_VERSION = "H2_H3_FOLLOWUP_DESCRIPTIVE_V1"

DISCOVERY_START_SESSION_DATE = "2026-09-04"
FROZEN_THROUGH_SESSION_DATE = "2026-09-17"
PROSPECTIVE_START_SESSION_DATE = "2026-09-18"

DESCRIPTIVE_MILESTONE_DATES = 5
SERIOUS_REVIEW_MILESTONE_DATES = 20
MILESTONES = (
    DESCRIPTIVE_MILESTONE_DATES,
    SERIOUS_REVIEW_MILESTONE_DATES,
)

H2_KEY = "H2_RAW_MODEL_FORM_CONFIRMATION"
H3_KEY = "H3_MARKET_QUALITY_MONOTONIC_CONFIRMATION"

DTE_BUCKETS = (
    "DTE_07_13",
    "DTE_14_20",
    "DTE_21_30",
    "DTE_31_45",
)


class FollowupConfirmationError(RuntimeError):
    pass


@dataclass(frozen=True)
class FollowupFreezeResult:
    program_id: int
    program_key: str
    protocol_version: str
    frozen_at: str
    frozen_through_session_date: str
    prospective_start_session_date: str
    source_original_freeze_run_id: int
    config_hash: str
    created: bool


@dataclass(frozen=True)
class FollowupEvaluation:
    hypothesis_key: str
    milestone_date_count: int
    evidence_start_session_date: str
    evidence_end_session_date: str
    observation_count: int
    evaluation_state: str
    metrics: dict[str, Any]
    persisted_evaluation_id: int | None


@dataclass(frozen=True)
class FollowupConfirmationResult:
    program_id: int
    program_key: str
    evaluation_version: str
    available_independent_dates: int
    available_session_dates: tuple[str, ...]
    evaluations: tuple[FollowupEvaluation, ...]


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def _canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    )


def _hash_json(payload: dict[str, Any]) -> tuple[str, str]:
    encoded = _canonical_json(payload)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest(), encoded


def _dte_bucket(dte: int) -> str | None:
    if 7 <= dte <= 13:
        return "DTE_07_13"
    if 14 <= dte <= 20:
        return "DTE_14_20"
    if 21 <= dte <= 30:
        return "DTE_21_30"
    if 31 <= dte <= 45:
        return "DTE_31_45"
    return None


def _single_identity(rows, *, label: str) -> dict[str, Any]:
    materialized = [dict(row) for row in rows]
    if len(materialized) != 1:
        raise FollowupConfirmationError(
            f"{label} must resolve to exactly one frozen discovery identity; "
            f"found {len(materialized)}."
        )
    return materialized[0]


def _source_original_freeze(conn):
    freeze = conn.execute(
        """
        SELECT *
        FROM prospective_research_freeze_v1_runs
        ORDER BY id DESC
        LIMIT 1;
        """
    ).fetchone()
    if freeze is None:
        raise FollowupConfirmationError(
            "The original H1-H4 prospective freeze does not exist."
        )
    if str(freeze["frozen_through_session_date"]) >= DISCOVERY_START_SESSION_DATE:
        raise FollowupConfirmationError(
            "Original prospective freeze boundary is incompatible with the "
            "Sep-04 through Sep-17 discovery window."
        )
    if str(freeze["prospective_start_session_date"]) > DISCOVERY_START_SESSION_DATE:
        raise FollowupConfirmationError(
            "Original prospective start is later than the follow-up discovery window."
        )
    return freeze


def _discovery_identities(conn) -> tuple[dict[str, Any], dict[str, Any]]:
    scanner = _single_identity(
        conn.execute(
            """
            SELECT DISTINCT
                hsr.scanner_family_id,
                hsr.scanner_version,
                hsr.rule_version,
                hsr.hypothesis_family,
                hsr.hypothesis_version,
                hsr.config_hash
            FROM hypothesis_scanner_runs AS hsr
            JOIN research_runs AS rr
              ON rr.id = hsr.research_run_id
            WHERE rr.status = 'COMPLETED'
              AND rr.us_session_date BETWEEN ? AND ?;
            """,
            (
                DISCOVERY_START_SESSION_DATE,
                FROZEN_THROUGH_SESSION_DATE,
            ),
        ).fetchall(),
        label="V1 local-linear scanner identity",
    )

    quadratic = _single_identity(
        conn.execute(
            """
            SELECT DISTINCT
                lsr.model_family_id,
                lsr.model_version,
                lsr.fit_spec_version,
                lsr.config_hash
            FROM local_surface_residual_v2_runs AS lsr
            JOIN research_runs AS rr
              ON rr.id = lsr.research_run_id
            WHERE rr.status = 'COMPLETED'
              AND rr.us_session_date BETWEEN ? AND ?;
            """,
            (
                DISCOVERY_START_SESSION_DATE,
                FROZEN_THROUGH_SESSION_DATE,
            ),
        ).fetchall(),
        label="quadratic V2 identity",
    )

    return scanner, quadratic


def _protocol_config(
    *,
    scanner_identity: dict[str, Any],
    quadratic_identity: dict[str, Any],
) -> dict[str, Any]:
    return {
        "program_key": PROGRAM_KEY,
        "protocol_version": PROTOCOL_VERSION,
        "frozen_through_session_date": FROZEN_THROUGH_SESSION_DATE,
        "prospective_start_session_date": PROSPECTIVE_START_SESSION_DATE,
        "review_milestones_independent_dates": list(MILESTONES),
        "inference_firewall": {
            "p_values_enabled": False,
            "fdr_enabled": False,
            "admission_enabled": False,
            "model_promotion_enabled": False,
            "decision_enabled": False,
        },
        "frozen_model_identity": {
            "local_linear_v1": scanner_identity,
            "quadratic_v2": quadratic_identity,
        },
        "h2": {
            "hypothesis_key": H2_KEY,
            "primary_population": "ALL_PAIRED_EVALUABLE",
            "primary_population_role": "PRIMARY_CONFIRMATORY_FOLLOWUP",
            "paired_comparison": (
                "abs(actual persisted V1 nearest-bracket local-linear residual) "
                "vs abs(raw quadratic V2 leave-one-out residual)"
            ),
            "dte_buckets": list(DTE_BUCKETS),
            "metrics": [
                "median_absolute_residual",
                "q95_absolute_residual",
                "local_linear_better_fraction",
            ],
            "secondary_clean_population": {
                "role": "PRESPECIFIED_SECONDARY_DISCOVERY_INFORMED",
                "spread_to_mid_lt": 0.05,
                "abs_greek_age_seconds_lte": 1.0,
            },
            "pooled_observations_as_independent_evidence": False,
            "automatic_model_selection": False,
        },
        "h3": {
            "hypothesis_key": H3_KEY,
            "residual_basis": "FROZEN_NULL_CENTERED_QUADRATIC_V2",
            "unit": "INDEPENDENT_SESSION_DATE_X_DTE_BUCKET",
            "dte_buckets": list(DTE_BUCKETS),
            "spread_buckets": [
                "LT_05",
                "05_10",
                "10_20",
            ],
            "greek_age_buckets": [
                "LE_1S",
                "1_5S",
                "5_30S",
            ],
            "primary_descriptor": (
                "strict monotonic increase in mean absolute centered residual "
                "as market quality worsens within date x DTE"
            ),
            "automatic_threshold_change": False,
        },
    }


def _discovery_context() -> dict[str, Any]:
    return {
        "classification": "RETROSPECTIVE_DISCOVERY_SUPPORTING_FOLLOWUP_NOT_CONFIRMATION",
        "window": {
            "start_session_date": DISCOVERY_START_SESSION_DATE,
            "end_session_date": FROZEN_THROUGH_SESSION_DATE,
            "independent_session_dates": 6,
        },
        "h2": {
            "production_v1_parity": {
                "evaluable_observations": 969048,
                "geometry_mismatches": 0,
                "residual_mismatches_gt_1e_12": 0,
                "max_abs_residual_difference": 1.1102230246251565e-16,
            },
            "h2_v2_overlap_parity": {
                "comparable_observations": 965689,
                "missing_in_v1": 0,
                "residual_mismatches_gt_1e_12": 0,
                "max_abs_residual_difference": 1.1102230246251565e-16,
                "v1_evaluable_observations": 969048,
                "v2_not_evaluable_gap": 3359,
                "missing_v2_observations": 0,
                "v2_not_evaluable_reasons": {
                    "INSUFFICIENT_USABLE_STRIKES": {
                        "usable_strikes_3": 835,
                        "usable_strikes_4": 2524,
                        "total": 3359,
                    },
                },
                "per_date_gap": {
                    "2026-09-04": 779,
                    "2026-09-11": 53,
                    "2026-09-14": 885,
                    "2026-09-15": 594,
                    "2026-09-16": 695,
                    "2026-09-17": 353,
                },
                "minimum_geometry_rule": {
                    "min_usable_strikes": 5,
                    "quadratic_parameter_count": 3,
                    "loo_peer_count_at_minimum": 4,
                    "residual_degrees_of_freedom_at_minimum": 1,
                    "documented_rationale": (
                        "Five usable strikes leave four peers after target "
                        "omission for a three-parameter quadratic, preserving "
                        "one positive residual degree of freedom."
                    ),
                    "audit_boundary": (
                        "This reconciliation verifies consistent enforcement "
                        "and fully explains the population gap; it does not "
                        "independently establish that five is statistically optimal."
                    ),
                },
                "gap_reconciliation_state": "FULLY_EXPLAINED_BY_V2_MINIMUM_GEOMETRY",
            },
            "raw_vs_raw_all_population": {
                "date_x_dte_cells": 24,
                "local_linear_lower_median_cells": 24,
                "local_linear_lower_q95_cells": 20,
                "local_linear_better_fraction_gt_half_cells": 24,
                "local_linear_better_fraction_range": [0.5433, 0.6892],
            },
            "raw_vs_centered_selection_audit": {
                "raw_better_consistently_exceeds_centered": False,
                "selection_rationale": (
                    "Raw-vs-raw is the symmetric paired model comparison and "
                    "was selected even though centered often produced the more "
                    "favorable local-linear better-fraction."
                ),
                "centered_higher_examples_all_population": [
                    {
                        "session_date": "2026-09-14",
                        "dte_bucket": "DTE_21_30",
                        "raw_better_fraction": 0.6686,
                        "centered_better_fraction": 0.6867,
                    },
                    {
                        "session_date": "2026-09-16",
                        "dte_bucket": "DTE_31_45",
                        "raw_better_fraction": 0.6622,
                        "centered_better_fraction": 0.6808,
                    },
                    {
                        "session_date": "2026-09-17",
                        "dte_bucket": "DTE_21_30",
                        "raw_better_fraction": 0.6583,
                        "centered_better_fraction": 0.6828,
                    },
                ],
            },
            "clean_population": {
                "date_x_dte_cells": 24,
                "local_linear_lower_median_cells": 24,
                "local_linear_lower_q95_cells": 24,
                "selection_note": (
                    "The thresholds pre-existed in frozen H3, but elevating this "
                    "lens occurred after observing Sep-04 through Sep-17. It is "
                    "therefore secondary, not the primary confirmation population."
                ),
            },
            "sep04": {
                "weaker_date_retained": True,
                "missing_early_slots_explain_weakness": False,
                "exclusion_or_rewrite_allowed": False,
            },
            "legacy_centering_note": (
                "The original H2 checkpoint compared local-linear raw residuals "
                "with frozen-null-centered quadratic residuals. The follow-up "
                "primary endpoint uses symmetric raw-vs-raw paired residuals. "
                "This endpoint choice is discovery-informed and is confirmatory "
                "only for observations collected after the new freeze."
            ),
        },
        "h3": {
            "spread_monotonic_cells": "24/24",
            "greek_age_monotonic_cells": "24/24",
            "total_strict_monotonic_cells": "48/48",
            "confirmation_note": (
                "The observed perfect monotonicity motivates the follow-up; it "
                "is not itself future confirmation."
            ),
        },
    }


def freeze_h2_h3_followup_confirmation_v1(
    *,
    db_path=None,
) -> FollowupFreezeResult:
    conn = get_connection(db_path)
    try:
        existing = conn.execute(
            """
            SELECT *
            FROM prospective_followup_programs_v1
            WHERE program_key = ?;
            """,
            (PROGRAM_KEY,),
        ).fetchone()

        if existing is not None:
            return FollowupFreezeResult(
                program_id=int(existing["id"]),
                program_key=str(existing["program_key"]),
                protocol_version=str(existing["protocol_version"]),
                frozen_at=str(existing["frozen_at"]),
                frozen_through_session_date=str(
                    existing["frozen_through_session_date"]
                ),
                prospective_start_session_date=str(
                    existing["prospective_start_session_date"]
                ),
                source_original_freeze_run_id=int(
                    existing["source_original_freeze_run_id"]
                ),
                config_hash=str(existing["config_hash"]),
                created=False,
            )

        post_boundary_runs = int(
            conn.execute(
                """
                SELECT COUNT(*)
                FROM research_runs
                WHERE status = 'COMPLETED'
                  AND us_session_date >= ?;
                """,
                (PROSPECTIVE_START_SESSION_DATE,),
            ).fetchone()[0]
        )
        if post_boundary_runs:
            raise FollowupConfirmationError(
                "Follow-up freeze refused: completed research evidence already "
                f"exists on or after {PROSPECTIVE_START_SESSION_DATE}."
            )

        source_freeze = _source_original_freeze(conn)
        scanner_identity, quadratic_identity = _discovery_identities(conn)

        config = _protocol_config(
            scanner_identity=scanner_identity,
            quadratic_identity=quadratic_identity,
        )
        config_hash, config_json = _hash_json(config)
        discovery_json = _canonical_json(_discovery_context())
        frozen_at = _utc_now()

        h2_selection = {
            "primary": "ALL_PAIRED_EVALUABLE",
            "primary_selection_timing": (
                "Chosen after Sep-04 through Sep-17 methodological audit; "
                "confirmatory authority begins only after this freeze."
            ),
            "secondary_clean": {
                "definition": "spread_to_mid < 0.05 AND abs(greek_age_seconds) <= 1",
                "provenance": "DISCOVERY_INFORMED_SECONDARY",
            },
        }
        h3_selection = {
            "bucket_boundaries": "PRE_EXISTING_FROZEN_H3_BOUNDARIES",
            "followup_motivation": "DISCOVERY_INFORMED_48_OF_48_MONOTONIC_CELLS",
            "future_authority": "PROSPECTIVE_ONLY_AFTER_NEW_FREEZE",
        }

        with conn:
            cursor = conn.execute(
                """
                INSERT INTO prospective_followup_programs_v1 (
                    program_key,
                    protocol_version,
                    source_original_freeze_run_id,
                    frozen_at,
                    frozen_through_session_date,
                    prospective_start_session_date,
                    protocol_state,
                    config_hash,
                    config_json,
                    discovery_context_json,
                    p_values_enabled,
                    fdr_enabled,
                    admission_enabled,
                    model_promotion_enabled,
                    decision_enabled
                ) VALUES (
                    ?, ?, ?, ?, ?, ?,
                    'FROZEN_FOLLOWUP_OBSERVATION_ONLY',
                    ?, ?, ?,
                    0, 0, 0, 0, 0
                );
                """,
                (
                    PROGRAM_KEY,
                    PROTOCOL_VERSION,
                    int(source_freeze["id"]),
                    frozen_at,
                    FROZEN_THROUGH_SESSION_DATE,
                    PROSPECTIVE_START_SESSION_DATE,
                    config_hash,
                    config_json,
                    discovery_json,
                ),
            )
            program_id = int(cursor.lastrowid)

            conn.execute(
                """
                INSERT INTO prospective_followup_hypotheses_v1 (
                    program_id,
                    hypothesis_key,
                    description,
                    primary_unit,
                    primary_metric_family,
                    minimum_independent_dates,
                    serious_review_independent_dates,
                    selection_provenance_json,
                    hypothesis_state,
                    decision_enabled
                ) VALUES (
                    ?, ?, ?,
                    'INDEPENDENT_SESSION_DATE_WITH_PAIRED_OPTION_OBSERVATIONS',
                    'PAIRED_RAW_RESIDUAL_MODEL_FORM_CONFIRMATION_V1',
                    5, 20, ?,
                    'FROZEN_FOLLOWUP_PROSPECTIVE',
                    0
                );
                """,
                (
                    program_id,
                    H2_KEY,
                    (
                        "Confirm whether persisted V1 nearest-bracket "
                        "local-linear residuals generalize against raw "
                        "quadratic V2 LOO residuals on fresh paired "
                        "observations."
                    ),
                    _canonical_json(h2_selection),
                ),
            )

            conn.execute(
                """
                INSERT INTO prospective_followup_hypotheses_v1 (
                    program_id,
                    hypothesis_key,
                    description,
                    primary_unit,
                    primary_metric_family,
                    minimum_independent_dates,
                    serious_review_independent_dates,
                    selection_provenance_json,
                    hypothesis_state,
                    decision_enabled
                ) VALUES (
                    ?, ?, ?,
                    'INDEPENDENT_SESSION_DATE_X_DTE_BUCKET',
                    'MARKET_QUALITY_MONOTONIC_CONFIRMATION_V1',
                    5, 20, ?,
                    'FROZEN_FOLLOWUP_PROSPECTIVE',
                    0
                );
                """,
                (
                    program_id,
                    H3_KEY,
                    (
                        "Confirm whether worse spread and Greek freshness "
                        "buckets show strictly increasing residual scale "
                        "within fresh independent date x DTE cells."
                    ),
                    _canonical_json(h3_selection),
                ),
            )

        return FollowupFreezeResult(
            program_id=program_id,
            program_key=PROGRAM_KEY,
            protocol_version=PROTOCOL_VERSION,
            frozen_at=frozen_at,
            frozen_through_session_date=FROZEN_THROUGH_SESSION_DATE,
            prospective_start_session_date=PROSPECTIVE_START_SESSION_DATE,
            source_original_freeze_run_id=int(source_freeze["id"]),
            config_hash=config_hash,
            created=True,
        )
    finally:
        conn.close()


def _program_context(*, db_path=None):
    conn = get_connection(db_path)
    try:
        program = conn.execute(
            """
            SELECT *
            FROM prospective_followup_programs_v1
            WHERE program_key = ?;
            """,
            (PROGRAM_KEY,),
        ).fetchone()
        if program is None:
            raise FollowupConfirmationError(
                "H2/H3 follow-up programme is not frozen. Run the explicit "
                "freeze command before collecting follow-up evidence."
            )

        hypotheses = conn.execute(
            """
            SELECT *
            FROM prospective_followup_hypotheses_v1
            WHERE program_id = ?
            ORDER BY hypothesis_key;
            """,
            (program["id"],),
        ).fetchall()

        source_freeze = conn.execute(
            """
            SELECT *
            FROM prospective_research_freeze_v1_runs
            WHERE id = ?;
            """,
            (program["source_original_freeze_run_id"],),
        ).fetchone()
        if source_freeze is None:
            raise FollowupConfirmationError(
                "Follow-up programme references a missing original freeze."
            )

        validity = conn.execute(
            """
            SELECT *
            FROM local_surface_calibration_validity_v1_runs
            WHERE id = ?;
            """,
            (source_freeze["source_validity_run_id"],),
        ).fetchone()
        if validity is None:
            raise FollowupConfirmationError(
                "Original freeze references missing calibration validity."
            )

        readiness = conn.execute(
            """
            SELECT *
            FROM local_surface_calibration_readiness_v1_runs
            WHERE id = ?;
            """,
            (validity["source_calibration_run_id"],),
        ).fetchone()
        if readiness is None:
            raise FollowupConfirmationError(
                "Calibration validity references missing readiness evidence."
            )

        null_run_id = int(readiness["source_null_run_id"])
    finally:
        conn.close()

    return (
        dict(program),
        [dict(row) for row in hypotheses],
        null_run_id,
    )


def _identity_from_program(program: dict[str, Any]):
    config = json.loads(str(program["config_json"]))
    identity = config["frozen_model_identity"]
    return identity["local_linear_v1"], identity["quadratic_v2"]


def _eligible_dates(
    *,
    program: dict[str, Any],
    db_path=None,
) -> tuple[str, ...]:
    scanner, quadratic = _identity_from_program(program)
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            """
            WITH exact_scanner_runs AS (
                SELECT
                    research_run_id,
                    MIN(id) AS scanner_run_id,
                    COUNT(*) AS scanner_run_count
                FROM hypothesis_scanner_runs
                WHERE scanner_family_id = ?
                  AND scanner_version = ?
                  AND rule_version = ?
                  AND hypothesis_family = ?
                  AND hypothesis_version = ?
                  AND config_hash = ?
                GROUP BY research_run_id
                HAVING COUNT(*) = 1
            )
            SELECT DISTINCT p.us_session_date
            FROM v_h2_h3_followup_partition_v1 AS p
            JOIN exact_scanner_runs AS esr
              ON esr.research_run_id = p.research_run_id
            JOIN hypothesis_scanner_evaluations AS hse
              ON hse.scanner_run_id = esr.scanner_run_id
             AND hse.option_quote_id = p.option_quote_id
            WHERE p.followup_program_id = ?
              AND p.followup_evidence_phase = 'FOLLOWUP_PROSPECTIVE'
              AND p.observation_state = 'EVALUATED_OBSERVATIONAL'
              AND p.loo_residual IS NOT NULL
              AND hse.iv_residual IS NOT NULL
              AND p.model_version = ?
              AND p.fit_spec_version = ?
              AND p.surface_config_hash = ?
            ORDER BY p.us_session_date;
            """,
            (
                scanner["scanner_family_id"],
                scanner["scanner_version"],
                scanner["rule_version"],
                scanner["hypothesis_family"],
                scanner["hypothesis_version"],
                scanner["config_hash"],
                int(program["id"]),
                quadratic["model_version"],
                quadratic["fit_spec_version"],
                quadratic["config_hash"],
            ),
        ).fetchall()
    finally:
        conn.close()
    return tuple(str(row["us_session_date"]) for row in rows)


def _session_placeholders(session_dates: tuple[str, ...]) -> str:
    if not session_dates:
        raise FollowupConfirmationError(
            "At least one session date is required for evaluation."
        )
    return ",".join("?" for _ in session_dates)


def _h2_bucket() -> dict[str, Any]:
    return {
        "quadratic": array("d"),
        "linear": array("d"),
        "linear_better": 0,
    }


def _h2_add(
    store: dict[tuple[str, str], dict[str, Any]],
    *,
    session_date: str,
    dte_bucket: str,
    quadratic_abs: float,
    linear_abs: float,
) -> None:
    bucket = store.setdefault(
        (session_date, dte_bucket),
        _h2_bucket(),
    )
    bucket["quadratic"].append(quadratic_abs)
    bucket["linear"].append(linear_abs)
    if linear_abs < quadratic_abs:
        bucket["linear_better"] += 1


def _h2_scope_summary(
    store: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any]:
    cells: list[dict[str, Any]] = []

    for session_date, dte_bucket in sorted(store):
        bucket = store[(session_date, dte_bucket)]
        quadratic = np.frombuffer(
            bucket["quadratic"],
            dtype=np.float64,
        )
        linear = np.frombuffer(
            bucket["linear"],
            dtype=np.float64,
        )
        if len(quadratic) == 0:
            continue

        cells.append(
            {
                "session_date": session_date,
                "dte_bucket": dte_bucket,
                "paired_observation_count": int(len(quadratic)),
                "quadratic_median_abs_residual": float(
                    np.median(quadratic)
                ),
                "local_linear_median_abs_residual": float(
                    np.median(linear)
                ),
                "quadratic_q95_abs_residual": float(
                    np.quantile(quadratic, 0.95)
                ),
                "local_linear_q95_abs_residual": float(
                    np.quantile(linear, 0.95)
                ),
                "local_linear_better_fraction": float(
                    int(bucket["linear_better"]) / len(quadratic)
                ),
            }
        )

    return {
        "date_x_dte_cell_count": len(cells),
        "paired_observation_count": int(
            sum(item["paired_observation_count"] for item in cells)
        ),
        "local_linear_lower_median_cell_count": sum(
            item["local_linear_median_abs_residual"]
            < item["quadratic_median_abs_residual"]
            for item in cells
        ),
        "local_linear_lower_q95_cell_count": sum(
            item["local_linear_q95_abs_residual"]
            < item["quadratic_q95_abs_residual"]
            for item in cells
        ),
        "local_linear_better_fraction_gt_half_cell_count": sum(
            item["local_linear_better_fraction"] > 0.5
            for item in cells
        ),
        "by_date_dte": cells,
    }


def _h2_metrics(
    *,
    program: dict[str, Any],
    session_dates: tuple[str, ...],
    db_path=None,
) -> tuple[dict[str, Any], int]:
    scanner, quadratic = _identity_from_program(program)
    placeholders = _session_placeholders(session_dates)

    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            f"""
            WITH exact_scanner_runs AS (
                SELECT
                    research_run_id,
                    MIN(id) AS scanner_run_id,
                    COUNT(*) AS scanner_run_count
                FROM hypothesis_scanner_runs
                WHERE scanner_family_id = ?
                  AND scanner_version = ?
                  AND rule_version = ?
                  AND hypothesis_family = ?
                  AND hypothesis_version = ?
                  AND config_hash = ?
                GROUP BY research_run_id
                HAVING COUNT(*) = 1
            )
            SELECT
                p.us_session_date,
                p.dte,
                p.spread_to_mid,
                p.greek_age_seconds,
                p.loo_residual AS quadratic_raw_residual,
                hse.iv_residual AS local_linear_residual
            FROM v_h2_h3_followup_partition_v1 AS p
            JOIN exact_scanner_runs AS esr
              ON esr.research_run_id = p.research_run_id
            JOIN hypothesis_scanner_evaluations AS hse
              ON hse.scanner_run_id = esr.scanner_run_id
             AND hse.option_quote_id = p.option_quote_id
            WHERE p.followup_program_id = ?
              AND p.followup_evidence_phase = 'FOLLOWUP_PROSPECTIVE'
              AND p.us_session_date IN ({placeholders})
              AND p.observation_state = 'EVALUATED_OBSERVATIONAL'
              AND p.loo_residual IS NOT NULL
              AND hse.iv_residual IS NOT NULL
              AND p.dte BETWEEN 7 AND 45
              AND p.model_version = ?
              AND p.fit_spec_version = ?
              AND p.surface_config_hash = ?
            ORDER BY
                p.us_session_date,
                p.research_run_id,
                p.underlying,
                p.expiration,
                p.right,
                p.strike;
            """,
            (
                scanner["scanner_family_id"],
                scanner["scanner_version"],
                scanner["rule_version"],
                scanner["hypothesis_family"],
                scanner["hypothesis_version"],
                scanner["config_hash"],
                int(program["id"]),
                *session_dates,
                quadratic["model_version"],
                quadratic["fit_spec_version"],
                quadratic["config_hash"],
            ),
        )
        primary: dict[tuple[str, str], dict[str, Any]] = {}
        clean: dict[tuple[str, str], dict[str, Any]] = {}

        for row in rows:
            dte_bucket = _dte_bucket(int(row["dte"]))
            if dte_bucket is None:
                continue

            quadratic_abs = abs(float(row["quadratic_raw_residual"]))
            linear_abs = abs(float(row["local_linear_residual"]))
            session_date = str(row["us_session_date"])

            _h2_add(
                primary,
                session_date=session_date,
                dte_bucket=dte_bucket,
                quadratic_abs=quadratic_abs,
                linear_abs=linear_abs,
            )

            spread = row["spread_to_mid"]
            greek_age = row["greek_age_seconds"]
            is_clean = (
                spread is not None
                and greek_age is not None
                and float(spread) < 0.05
                and abs(float(greek_age)) <= 1.0
            )
            if is_clean:
                _h2_add(
                    clean,
                    session_date=session_date,
                    dte_bucket=dte_bucket,
                    quadratic_abs=quadratic_abs,
                    linear_abs=linear_abs,
                )
    finally:
        conn.close()

    primary_summary = _h2_scope_summary(primary)
    clean_summary = _h2_scope_summary(clean)

    metrics = {
        "metric_family": "PAIRED_RAW_RESIDUAL_MODEL_FORM_CONFIRMATION_V1",
        "evidence_session_dates": list(session_dates),
        "primary_all_population": {
            "role": "PRIMARY_CONFIRMATORY_FOLLOWUP",
            "definition": "ALL_PAIRED_EVALUABLE",
            **primary_summary,
        },
        "secondary_clean_population": {
            "role": "PRESPECIFIED_SECONDARY_DISCOVERY_INFORMED",
            "definition": (
                "spread_to_mid < 0.05 AND abs(greek_age_seconds) <= 1"
            ),
            "selection_provenance": (
                "Thresholds pre-existed in H3; the choice to emphasize this "
                "subgroup was made after Sep-04 through Sep-17 inspection."
            ),
            **clean_summary,
        },
        "independence_note": (
            "Option rows are paired model-error observations. Cross-date "
            "consistency is reported by session date x DTE; pooled row count "
            "is not treated as the independent sample size."
        ),
        "guardrail": (
            "No automatic model promotion, admission change, edge claim, "
            "p-value, FDR decision, or trading decision is enabled."
        ),
    }
    return metrics, int(primary_summary["paired_observation_count"])


def _h3_metrics(
    *,
    program: dict[str, Any],
    null_run_id: int,
    session_dates: tuple[str, ...],
    db_path=None,
) -> tuple[dict[str, Any], int]:
    _scanner, quadratic = _identity_from_program(program)
    placeholders = _session_placeholders(session_dates)

    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            f"""
            WITH base AS (
                SELECT
                    p.*,
                    CASE
                        WHEN p.dte BETWEEN 7 AND 13 THEN 'DTE_07_13'
                        WHEN p.dte BETWEEN 14 AND 20 THEN 'DTE_14_20'
                        WHEN p.dte BETWEEN 21 AND 30 THEN 'DTE_21_30'
                        WHEN p.dte BETWEEN 31 AND 45 THEN 'DTE_31_45'
                        ELSE 'DTE_OTHER'
                    END AS dte_bucket,
                    CASE
                        WHEN p.abs_delta >= 0.10 AND p.abs_delta < 0.25
                            THEN 'ABSDELTA_10_25'
                        WHEN p.abs_delta >= 0.25 AND p.abs_delta < 0.40
                            THEN 'ABSDELTA_25_40'
                        WHEN p.abs_delta >= 0.40 AND p.abs_delta < 0.60
                            THEN 'ABSDELTA_40_60'
                        WHEN p.abs_delta >= 0.60 AND p.abs_delta <= 0.80
                            THEN 'ABSDELTA_60_80'
                        ELSE 'ABSDELTA_OTHER'
                    END AS abs_delta_bucket
                FROM v_h2_h3_followup_partition_v1 AS p
                WHERE p.followup_program_id = ?
                  AND p.followup_evidence_phase = 'FOLLOWUP_PROSPECTIVE'
                  AND p.us_session_date IN ({placeholders})
                  AND p.observation_state = 'EVALUATED_OBSERVATIONAL'
                  AND p.loo_residual IS NOT NULL
                  AND p.abs_delta IS NOT NULL
                  AND p.dte BETWEEN 7 AND 45
                  AND p.model_version = ?
                  AND p.fit_spec_version = ?
                  AND p.surface_config_hash = ?
            ), centered AS (
                SELECT
                    b.*,
                    b.loo_residual - n.shrunk_location AS centered_residual
                FROM base AS b
                LEFT JOIN local_surface_null_v1_strata AS n
                  ON n.null_run_id = ?
                 AND n.stratum_key = (
                     b.right || '|' || b.dte_bucket || '|' || b.abs_delta_bucket
                 )
            )
            SELECT
                us_session_date,
                dte_bucket,
                COUNT(centered_residual) AS centered_observation_count,

                SUM(CASE
                    WHEN spread_to_mid < 0.05
                    THEN 1 ELSE 0 END
                ) AS spread_n_lt05,
                AVG(CASE
                    WHEN spread_to_mid < 0.05
                    THEN ABS(centered_residual) END
                ) AS spread_mean_lt05,

                SUM(CASE
                    WHEN spread_to_mid >= 0.05
                     AND spread_to_mid < 0.10
                    THEN 1 ELSE 0 END
                ) AS spread_n_05_10,
                AVG(CASE
                    WHEN spread_to_mid >= 0.05
                     AND spread_to_mid < 0.10
                    THEN ABS(centered_residual) END
                ) AS spread_mean_05_10,

                SUM(CASE
                    WHEN spread_to_mid >= 0.10
                     AND spread_to_mid < 0.20
                    THEN 1 ELSE 0 END
                ) AS spread_n_10_20,
                AVG(CASE
                    WHEN spread_to_mid >= 0.10
                     AND spread_to_mid < 0.20
                    THEN ABS(centered_residual) END
                ) AS spread_mean_10_20,

                SUM(CASE
                    WHEN ABS(greek_age_seconds) <= 1
                    THEN 1 ELSE 0 END
                ) AS greek_n_le1,
                AVG(CASE
                    WHEN ABS(greek_age_seconds) <= 1
                    THEN ABS(centered_residual) END
                ) AS greek_mean_le1,

                SUM(CASE
                    WHEN ABS(greek_age_seconds) > 1
                     AND ABS(greek_age_seconds) <= 5
                    THEN 1 ELSE 0 END
                ) AS greek_n_1_5,
                AVG(CASE
                    WHEN ABS(greek_age_seconds) > 1
                     AND ABS(greek_age_seconds) <= 5
                    THEN ABS(centered_residual) END
                ) AS greek_mean_1_5,

                SUM(CASE
                    WHEN ABS(greek_age_seconds) > 5
                     AND ABS(greek_age_seconds) <= 30
                    THEN 1 ELSE 0 END
                ) AS greek_n_5_30,
                AVG(CASE
                    WHEN ABS(greek_age_seconds) > 5
                     AND ABS(greek_age_seconds) <= 30
                    THEN ABS(centered_residual) END
                ) AS greek_mean_5_30

            FROM centered
            WHERE dte_bucket != 'DTE_OTHER'
              AND centered_residual IS NOT NULL
            GROUP BY us_session_date, dte_bucket
            ORDER BY us_session_date, dte_bucket;
            """,
            (
                int(program["id"]),
                *session_dates,
                quadratic["model_version"],
                quadratic["fit_spec_version"],
                quadratic["config_hash"],
                int(null_run_id),
            ),
        ).fetchall()
    finally:
        conn.close()

    cells: list[dict[str, Any]] = []
    spread_evaluable = 0
    spread_monotonic = 0
    greek_evaluable = 0
    greek_monotonic = 0
    observation_count = 0

    for row in rows:
        observation_count += int(row["centered_observation_count"] or 0)

        spread_values = (
            row["spread_mean_lt05"],
            row["spread_mean_05_10"],
            row["spread_mean_10_20"],
        )
        spread_counts = (
            int(row["spread_n_lt05"] or 0),
            int(row["spread_n_05_10"] or 0),
            int(row["spread_n_10_20"] or 0),
        )
        spread_ok = (
            all(value is not None for value in spread_values)
            and all(count > 0 for count in spread_counts)
        )
        spread_strict = (
            bool(
                float(spread_values[0])
                < float(spread_values[1])
                < float(spread_values[2])
            )
            if spread_ok
            else None
        )
        if spread_ok:
            spread_evaluable += 1
            spread_monotonic += int(bool(spread_strict))

        greek_values = (
            row["greek_mean_le1"],
            row["greek_mean_1_5"],
            row["greek_mean_5_30"],
        )
        greek_counts = (
            int(row["greek_n_le1"] or 0),
            int(row["greek_n_1_5"] or 0),
            int(row["greek_n_5_30"] or 0),
        )
        greek_ok = (
            all(value is not None for value in greek_values)
            and all(count > 0 for count in greek_counts)
        )
        greek_strict = (
            bool(
                float(greek_values[0])
                < float(greek_values[1])
                < float(greek_values[2])
            )
            if greek_ok
            else None
        )
        if greek_ok:
            greek_evaluable += 1
            greek_monotonic += int(bool(greek_strict))

        cells.append(
            {
                "session_date": str(row["us_session_date"]),
                "dte_bucket": str(row["dte_bucket"]),
                "centered_observation_count": int(
                    row["centered_observation_count"] or 0
                ),
                "spread": {
                    "LT_05": {
                        "n": spread_counts[0],
                        "mean_abs_centered_residual": spread_values[0],
                    },
                    "05_10": {
                        "n": spread_counts[1],
                        "mean_abs_centered_residual": spread_values[1],
                    },
                    "10_20": {
                        "n": spread_counts[2],
                        "mean_abs_centered_residual": spread_values[2],
                    },
                    "strict_monotonic": spread_strict,
                },
                "greek_age": {
                    "LE_1S": {
                        "n": greek_counts[0],
                        "mean_abs_centered_residual": greek_values[0],
                    },
                    "1_5S": {
                        "n": greek_counts[1],
                        "mean_abs_centered_residual": greek_values[1],
                    },
                    "5_30S": {
                        "n": greek_counts[2],
                        "mean_abs_centered_residual": greek_values[2],
                    },
                    "strict_monotonic": greek_strict,
                },
            }
        )

    metrics = {
        "metric_family": "MARKET_QUALITY_MONOTONIC_CONFIRMATION_V1",
        "residual_basis": "FROZEN_NULL_CENTERED_QUADRATIC_V2",
        "evidence_session_dates": list(session_dates),
        "date_x_dte_cells": cells,
        "spread_summary": {
            "evaluable_date_x_dte_cells": spread_evaluable,
            "strict_monotonic_cells": spread_monotonic,
        },
        "greek_age_summary": {
            "evaluable_date_x_dte_cells": greek_evaluable,
            "strict_monotonic_cells": greek_monotonic,
        },
        "guardrail": (
            "Strict monotonicity is a descriptive replication target, not a "
            "causal estimate or tradable-edge claim. No threshold is changed "
            "from these observations."
        ),
    }
    return metrics, observation_count


def _persist_evaluation(
    *,
    program: dict[str, Any],
    hypothesis: dict[str, Any],
    milestone: int,
    session_dates: tuple[str, ...],
    observation_count: int,
    metrics: dict[str, Any],
    db_path=None,
) -> int:
    conn = get_connection(db_path)
    try:
        existing = conn.execute(
            """
            SELECT id
            FROM prospective_followup_evaluations_v1
            WHERE program_id = ?
              AND hypothesis_id = ?
              AND evaluation_version = ?
              AND milestone_date_count = ?;
            """,
            (
                int(program["id"]),
                int(hypothesis["id"]),
                EVALUATION_VERSION,
                milestone,
            ),
        ).fetchone()
        if existing is not None:
            return int(existing["id"])

        state = (
            "DESCRIPTIVE_5_DATE_CHECKPOINT"
            if milestone == DESCRIPTIVE_MILESTONE_DATES
            else "SERIOUS_20_DATE_REVIEW"
        )

        with conn:
            cursor = conn.execute(
                """
                INSERT INTO prospective_followup_evaluations_v1 (
                    program_id,
                    hypothesis_id,
                    hypothesis_key,
                    evaluation_version,
                    milestone_date_count,
                    evaluated_at,
                    evidence_start_session_date,
                    evidence_end_session_date,
                    independent_date_count,
                    observation_count,
                    evaluation_state,
                    metrics_json,
                    p_values_enabled,
                    fdr_enabled,
                    admission_enabled,
                    model_promotion_enabled,
                    decision_enabled
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    0, 0, 0, 0, 0
                );
                """,
                (
                    int(program["id"]),
                    int(hypothesis["id"]),
                    str(hypothesis["hypothesis_key"]),
                    EVALUATION_VERSION,
                    milestone,
                    _utc_now(),
                    session_dates[0],
                    session_dates[-1],
                    milestone,
                    int(observation_count),
                    state,
                    json.dumps(metrics, sort_keys=True),
                ),
            )
        return int(cursor.lastrowid)
    finally:
        conn.close()


def evaluate_h2_h3_followup_confirmation_v1(
    *,
    db_path=None,
    persist: bool = True,
) -> FollowupConfirmationResult:
    program, hypotheses, null_run_id = _program_context(db_path=db_path)
    by_key = {
        str(row["hypothesis_key"]): row
        for row in hypotheses
    }

    if set(by_key) != {H2_KEY, H3_KEY}:
        raise FollowupConfirmationError(
            "Frozen follow-up programme does not contain exactly H2 and H3."
        )

    available_dates = _eligible_dates(
        program=program,
        db_path=db_path,
    )

    evaluations: list[FollowupEvaluation] = []

    for milestone in MILESTONES:
        if len(available_dates) < milestone:
            continue

        milestone_dates = tuple(available_dates[:milestone])

        for hypothesis_key in (H2_KEY, H3_KEY):
            hypothesis = by_key[hypothesis_key]

            if hypothesis_key == H2_KEY:
                metrics, observation_count = _h2_metrics(
                    program=program,
                    session_dates=milestone_dates,
                    db_path=db_path,
                )
            else:
                metrics, observation_count = _h3_metrics(
                    program=program,
                    null_run_id=null_run_id,
                    session_dates=milestone_dates,
                    db_path=db_path,
                )

            metrics.update(
                {
                    "milestone_independent_dates": milestone,
                    "available_independent_dates_at_evaluation": len(
                        available_dates
                    ),
                    "p_values_enabled": False,
                    "fdr_enabled": False,
                    "admission_enabled": False,
                    "model_promotion_enabled": False,
                    "decision_enabled": False,
                }
            )

            persisted_id = None
            if persist:
                persisted_id = _persist_evaluation(
                    program=program,
                    hypothesis=hypothesis,
                    milestone=milestone,
                    session_dates=milestone_dates,
                    observation_count=observation_count,
                    metrics=metrics,
                    db_path=db_path,
                )

            state = (
                "DESCRIPTIVE_5_DATE_CHECKPOINT"
                if milestone == DESCRIPTIVE_MILESTONE_DATES
                else "SERIOUS_20_DATE_REVIEW"
            )

            evaluations.append(
                FollowupEvaluation(
                    hypothesis_key=hypothesis_key,
                    milestone_date_count=milestone,
                    evidence_start_session_date=milestone_dates[0],
                    evidence_end_session_date=milestone_dates[-1],
                    observation_count=observation_count,
                    evaluation_state=state,
                    metrics=metrics,
                    persisted_evaluation_id=persisted_id,
                )
            )

    return FollowupConfirmationResult(
        program_id=int(program["id"]),
        program_key=str(program["program_key"]),
        evaluation_version=EVALUATION_VERSION,
        available_independent_dates=len(available_dates),
        available_session_dates=available_dates,
        evaluations=tuple(evaluations),
    )


def freeze_result_as_dict(result: FollowupFreezeResult) -> dict[str, Any]:
    return asdict(result) | {
        "guardrail": (
            "Separate follow-up freeze only. The original H1-H4 prospective "
            "freeze and Sep-04 clock are untouched."
        )
    }


def result_as_dict(result: FollowupConfirmationResult) -> dict[str, Any]:
    return {
        "program_id": result.program_id,
        "program_key": result.program_key,
        "evaluation_version": result.evaluation_version,
        "available_independent_dates": result.available_independent_dates,
        "available_session_dates": list(result.available_session_dates),
        "evaluations": [asdict(item) for item in result.evaluations],
        "next_review_milestone": (
            DESCRIPTIVE_MILESTONE_DATES
            if result.available_independent_dates < DESCRIPTIVE_MILESTONE_DATES
            else SERIOUS_REVIEW_MILESTONE_DATES
            if result.available_independent_dates < SERIOUS_REVIEW_MILESTONE_DATES
            else None
        ),
        "guardrail": (
            "Follow-up confirmation is research-only. No automatic model "
            "promotion, admission change, edge claim, or trading authority."
        ),
    }
