from __future__ import annotations

from array import array
from dataclasses import asdict, dataclass
from datetime import datetime
import json
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import numpy as np

from src.database.repository import get_connection

UTC = ZoneInfo("UTC")
EVALUATION_VERSION = "PROSPECTIVE_DESCRIPTIVE_CHECKPOINT_V1"


class ProspectiveCheckpointError(RuntimeError):
    pass


@dataclass(frozen=True)
class HypothesisCheckpoint:
    hypothesis_key: str
    independent_date_count: int
    observation_count: int
    evaluation_state: str
    evidence_start_session_date: str | None
    evidence_end_session_date: str | None
    metrics: dict[str, Any]
    persisted_evaluation_id: int | None


@dataclass(frozen=True)
class ProspectiveCheckpointResult:
    freeze_run_id: int
    evaluation_version: str
    checkpoints: tuple[HypothesisCheckpoint, ...]


def _now_utc() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def _dte_bucket(dte: int) -> str:
    if 7 <= dte <= 13:
        return "DTE_07_13"
    if 14 <= dte <= 20:
        return "DTE_14_20"
    if 21 <= dte <= 30:
        return "DTE_21_30"
    if 31 <= dte <= 45:
        return "DTE_31_45"
    return "DTE_OTHER"


def _freeze_context(*, db_path=None):
    conn = get_connection(db_path)
    try:
        freeze = conn.execute(
            """
            SELECT *
            FROM prospective_research_freeze_v1_runs
            ORDER BY id DESC
            LIMIT 1;
            """
        ).fetchone()
        if freeze is None:
            raise ProspectiveCheckpointError(
                "No frozen prospective research protocol exists."
            )
        hypotheses = conn.execute(
            """
            SELECT *
            FROM prospective_research_hypotheses_v1
            WHERE freeze_run_id = ?
            ORDER BY id;
            """,
            (freeze["id"],),
        ).fetchall()
        validity = conn.execute(
            """
            SELECT *
            FROM local_surface_calibration_validity_v1_runs
            WHERE id = ?;
            """,
            (freeze["source_validity_run_id"],),
        ).fetchone()
        if validity is None:
            raise ProspectiveCheckpointError(
                "Frozen protocol references a missing calibration-validity run."
            )
        calibration = conn.execute(
            """
            SELECT *
            FROM local_surface_calibration_readiness_v1_runs
            WHERE id = ?;
            """,
            (validity["source_calibration_run_id"],),
        ).fetchone()
        if calibration is None:
            raise ProspectiveCheckpointError(
                "Calibration-validity run references missing readiness evidence."
            )
        null_run_id = int(calibration["source_null_run_id"])
    finally:
        conn.close()
    return dict(freeze), [dict(row) for row in hypotheses], null_run_id


def _coverage(*, db_path=None) -> dict[str, Any]:
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            """
            SELECT
                COUNT(*) AS observation_count,
                COUNT(DISTINCT us_session_date) AS independent_date_count,
                MIN(us_session_date) AS first_session_date,
                MAX(us_session_date) AS last_session_date
            FROM v_local_surface_v2_prospective_partition_v2
            WHERE evidence_phase = 'POST_FREEZE_PROSPECTIVE'
              AND observation_state = 'EVALUATED_OBSERVATIONAL'
              AND loo_residual IS NOT NULL;
            """
        ).fetchone()
    finally:
        conn.close()
    return dict(row)


def _centered_cte() -> str:
    """Frozen-null centering used only for descriptive prospective review."""
    return """
    WITH prospective AS (
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
        FROM v_local_surface_v2_prospective_partition_v2 AS p
        WHERE p.evidence_phase = 'POST_FREEZE_PROSPECTIVE'
          AND p.observation_state = 'EVALUATED_OBSERVATIONAL'
          AND p.loo_residual IS NOT NULL
          AND p.abs_delta IS NOT NULL
          AND p.dte IS NOT NULL
    ), centered AS (
        SELECT
            p.*,
            n.shrunk_location,
            p.loo_residual - n.shrunk_location AS centered_residual,
            ABS(p.loo_residual - n.shrunk_location) AS abs_centered_residual
        FROM prospective AS p
        LEFT JOIN local_surface_null_v1_strata AS n
          ON n.null_run_id = ?
         AND n.stratum_key = (
             p.right || '|' || p.dte_bucket || '|' || p.abs_delta_bucket
         )
    )
    """


def _h1_metrics(*, null_run_id: int, db_path=None) -> dict[str, Any]:
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            _centered_cte()
            + """
            SELECT
                us_session_date,
                COUNT(*) AS observation_count,
                AVG(abs_centered_residual) AS mean_abs_centered_residual,
                MAX(abs_centered_residual) AS max_abs_centered_residual,
                SUM(CASE WHEN centered_residual > 0 THEN 1 ELSE 0 END) AS positive_count,
                SUM(CASE WHEN centered_residual < 0 THEN 1 ELSE 0 END) AS negative_count
            FROM centered
            WHERE dte_bucket = 'DTE_14_20'
              AND centered_residual IS NOT NULL
            GROUP BY us_session_date
            ORDER BY us_session_date;
            """,
            (null_run_id,),
        ).fetchall()
    finally:
        conn.close()
    return {
        "metric_family": "DTE_14_20_FROZEN_NULL_CENTERED_DESCRIPTIVE_V1",
        "per_date": [dict(row) for row in rows],
        "interpretation": (
            "Descriptive prospective checkpoint only. This does not reproduce "
            "the final empirical transfer-tail test and does not decide whether "
            "the frozen DTE 14-20 instability hypothesis is supported."
        ),
    }


def _flush_linear_group(
    group: list[Any],
    accumulators: dict[str, dict[str, Any]],
) -> None:
    ordered = sorted(
        [row for row in group if row["implied_volatility"] is not None],
        key=lambda row: float(row["strike"]),
    )
    for index, row in enumerate(ordered):
        if index == 0 or index == len(ordered) - 1:
            continue
        lo = ordered[index - 1]
        hi = ordered[index + 1]
        x = float(row["strike"])
        x0 = float(lo["strike"])
        x1 = float(hi["strike"])
        if x1 == x0 or row["centered_residual"] is None:
            continue
        y0 = float(lo["implied_volatility"])
        y1 = float(hi["implied_volatility"])
        fitted = y0 + (y1 - y0) * (x - x0) / (x1 - x0)
        linear_abs = abs(float(row["implied_volatility"]) - fitted)
        quadratic_abs = abs(float(row["centered_residual"]))
        bucket = _dte_bucket(int(row["dte"]))
        if bucket == "DTE_OTHER":
            continue
        acc = accumulators.setdefault(
            bucket,
            {
                "quadratic": array("d"),
                "linear": array("d"),
                "linear_better": 0,
            },
        )
        acc["quadratic"].append(quadratic_abs)
        acc["linear"].append(linear_abs)
        if linear_abs < quadratic_abs:
            acc["linear_better"] += 1


def _h2_metrics(*, null_run_id: int, db_path=None) -> dict[str, Any]:
    conn = get_connection(db_path)
    accumulators: dict[str, dict[str, Any]] = {}
    try:
        cursor = conn.execute(
            _centered_cte()
            + """
            SELECT
                research_run_id,
                underlying,
                expiration,
                right,
                strike,
                implied_volatility,
                dte,
                centered_residual
            FROM centered
            WHERE centered_residual IS NOT NULL
              AND implied_volatility IS NOT NULL
              AND dte BETWEEN 7 AND 45
            ORDER BY
                research_run_id,
                underlying,
                expiration,
                right,
                strike;
            """,
            (null_run_id,),
        )
        current_key = None
        group: list[Any] = []
        for row in cursor:
            key = (
                int(row["research_run_id"]),
                str(row["underlying"]),
                str(row["expiration"]),
                str(row["right"]),
            )
            if current_key is not None and key != current_key:
                _flush_linear_group(group, accumulators)
                group = []
            group.append(row)
            current_key = key
        if group:
            _flush_linear_group(group, accumulators)
    finally:
        conn.close()

    comparison = []
    for bucket in sorted(accumulators):
        acc = accumulators[bucket]
        q = np.frombuffer(acc["quadratic"], dtype=np.float64)
        linear = np.frombuffer(acc["linear"], dtype=np.float64)
        if len(q) == 0:
            continue
        comparison.append(
            {
                "dte_bucket": bucket,
                "observation_count": int(len(q)),
                "quadratic_median_abs_residual": float(np.median(q)),
                "local_linear_median_abs_residual": float(np.median(linear)),
                "quadratic_q95_abs_residual": float(np.quantile(q, 0.95)),
                "local_linear_q95_abs_residual": float(
                    np.quantile(linear, 0.95)
                ),
                "local_linear_better_fraction": float(
                    int(acc["linear_better"]) / len(q)
                ),
            }
        )
    return {
        "metric_family": "QUADRATIC_V2_VS_NEAREST_BRACKET_LINEAR_PROSPECTIVE_V1",
        "comparison_by_dte": comparison,
        "interpretation": (
            "Prospective descriptive model-form comparison using the frozen "
            "quadratic residual centering and the same nearest-bracket local-"
            "linear challenger concept used in discovery. No automatic model "
            "switching or trading decision is enabled."
        ),
    }


def _h3_metrics(*, null_run_id: int, db_path=None) -> dict[str, Any]:
    conn = get_connection(db_path)
    try:
        spread = conn.execute(
            _centered_cte()
            + """
            SELECT
                CASE
                    WHEN spread_to_mid IS NULL THEN 'MISSING'
                    WHEN spread_to_mid < 0.05 THEN 'LT_05'
                    WHEN spread_to_mid < 0.10 THEN '05_10'
                    WHEN spread_to_mid < 0.20 THEN '10_20'
                    ELSE 'GE_20'
                END AS quality_bucket,
                COUNT(*) AS observation_count,
                AVG(abs_centered_residual) AS mean_abs_centered_residual,
                MAX(abs_centered_residual) AS max_abs_centered_residual
            FROM centered
            WHERE centered_residual IS NOT NULL
            GROUP BY quality_bucket
            ORDER BY quality_bucket;
            """,
            (null_run_id,),
        ).fetchall()
        greek_age = conn.execute(
            _centered_cte()
            + """
            SELECT
                CASE
                    WHEN greek_age_seconds IS NULL THEN 'MISSING'
                    WHEN ABS(greek_age_seconds) <= 1 THEN 'LE_1S'
                    WHEN ABS(greek_age_seconds) <= 5 THEN '1_5S'
                    WHEN ABS(greek_age_seconds) <= 30 THEN '5_30S'
                    ELSE 'GT_30S'
                END AS quality_bucket,
                COUNT(*) AS observation_count,
                AVG(abs_centered_residual) AS mean_abs_centered_residual,
                MAX(abs_centered_residual) AS max_abs_centered_residual
            FROM centered
            WHERE centered_residual IS NOT NULL
            GROUP BY quality_bucket
            ORDER BY quality_bucket;
            """,
            (null_run_id,),
        ).fetchall()
    finally:
        conn.close()
    return {
        "metric_family": "MARKET_QUALITY_CONDITIONING_DESCRIPTIVE_V1",
        "spread_to_mid": [dict(row) for row in spread],
        "greek_age": [dict(row) for row in greek_age],
        "interpretation": (
            "Descriptive conditioning only. Differences across quality buckets "
            "are not causal estimates and are not evidence of tradable edge."
        ),
    }


def _h4_metrics(*, null_run_id: int, db_path=None) -> dict[str, Any]:
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            _centered_cte()
            + """
            , episodes AS (
                SELECT
                    underlying,
                    expiration,
                    strike,
                    right,
                    us_session_date,
                    COUNT(*) AS observation_count,
                    AVG(centered_residual) AS mean_centered_residual,
                    MAX(abs_centered_residual) AS peak_abs_centered_residual,
                    SUM(CASE WHEN centered_residual > 0 THEN 1 ELSE 0 END)
                        AS positive_count,
                    SUM(CASE WHEN centered_residual < 0 THEN 1 ELSE 0 END)
                        AS negative_count
                FROM centered
                WHERE centered_residual IS NOT NULL
                GROUP BY underlying, expiration, strike, right, us_session_date
            ), contracts AS (
                SELECT
                    underlying,
                    expiration,
                    strike,
                    right,
                    COUNT(*) AS session_date_count,
                    SUM(observation_count) AS total_observation_count,
                    AVG(ABS(mean_centered_residual)) AS mean_abs_episode_location,
                    MAX(peak_abs_centered_residual) AS max_peak_abs_residual,
                    SUM(CASE WHEN mean_centered_residual > 0 THEN 1 ELSE 0 END)
                        AS positive_episode_dates,
                    SUM(CASE WHEN mean_centered_residual < 0 THEN 1 ELSE 0 END)
                        AS negative_episode_dates
                FROM episodes
                GROUP BY underlying, expiration, strike, right
            )
            SELECT
                underlying,
                expiration,
                strike,
                right,
                session_date_count,
                total_observation_count,
                mean_abs_episode_location,
                max_peak_abs_residual,
                positive_episode_dates,
                negative_episode_dates,
                CASE
                    WHEN session_date_count > 0 THEN
                        CAST(MAX(positive_episode_dates, negative_episode_dates) AS REAL)
                        / session_date_count
                END AS cross_date_sign_agreement
            FROM contracts
            WHERE session_date_count >= 2
            ORDER BY
                session_date_count DESC,
                mean_abs_episode_location DESC,
                max_peak_abs_residual DESC
            LIMIT 100;
            """,
            (null_run_id,),
        ).fetchall()
    finally:
        conn.close()
    return {
        "metric_family": "PERSISTENT_EPISODE_RECURRENCE_DESCRIPTIVE_V1",
        "recurring_contract_count_in_top_view": len(rows),
        "top_recurring_contracts": [dict(row) for row in rows],
        "interpretation": (
            "Mean-based contract/session recurrence descriptors are used for "
            "this checkpoint to avoid treating millions of intraday rows as "
            "independent evidence. This is descriptive review, not a signal."
        ),
    }


def _metrics_for(
    hypothesis_key: str, *, null_run_id: int, db_path=None
) -> dict[str, Any]:
    if hypothesis_key == "H1_DTE_14_20_TRANSFER_STABILITY":
        return _h1_metrics(null_run_id=null_run_id, db_path=db_path)
    if hypothesis_key == "H2_MODEL_FORM_GENERALIZATION":
        return _h2_metrics(null_run_id=null_run_id, db_path=db_path)
    if hypothesis_key == "H3_MARKET_QUALITY_CONDITIONING":
        return _h3_metrics(null_run_id=null_run_id, db_path=db_path)
    if hypothesis_key == "H4_PERSISTENT_EPISODE_RECURRENCE":
        return _h4_metrics(null_run_id=null_run_id, db_path=db_path)
    return {
        "metric_family": "UNSUPPORTED_HYPOTHESIS",
        "interpretation": "No checkpoint implementation exists for this key.",
    }


def _persist_checkpoint(
    *,
    freeze_run_id: int,
    hypothesis: dict[str, Any],
    coverage: dict[str, Any],
    state: str,
    metrics: dict[str, Any],
    db_path=None,
) -> int:
    conn = get_connection(db_path)
    try:
        existing = conn.execute(
            """
            SELECT id
            FROM prospective_research_hypothesis_evaluations_v1
            WHERE freeze_run_id = ?
              AND hypothesis_id = ?
              AND evaluation_version = ?
              AND evidence_end_session_date IS ?;
            """,
            (
                freeze_run_id,
                hypothesis["id"],
                EVALUATION_VERSION,
                coverage["last_session_date"],
            ),
        ).fetchone()
        if existing is not None:
            return int(existing["id"])

        with conn:
            cursor = conn.execute(
                """
                INSERT INTO prospective_research_hypothesis_evaluations_v1 (
                    freeze_run_id, hypothesis_id, hypothesis_key,
                    evaluation_version, evaluated_at,
                    evidence_start_session_date, evidence_end_session_date,
                    independent_date_count, observation_count,
                    evaluation_state, metrics_json,
                    p_values_enabled, fdr_enabled, decision_enabled
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0);
                """,
                (
                    freeze_run_id,
                    hypothesis["id"],
                    hypothesis["hypothesis_key"],
                    EVALUATION_VERSION,
                    _now_utc(),
                    coverage["first_session_date"],
                    coverage["last_session_date"],
                    int(coverage["independent_date_count"] or 0),
                    int(coverage["observation_count"] or 0),
                    state,
                    json.dumps(metrics, sort_keys=True),
                ),
            )
        return int(cursor.lastrowid)
    finally:
        conn.close()


def evaluate_prospective_hypotheses_v1(
    *, db_path=None, persist: bool = True
) -> ProspectiveCheckpointResult:
    freeze, hypotheses, null_run_id = _freeze_context(db_path=db_path)
    coverage = _coverage(db_path=db_path)
    date_count = int(coverage["independent_date_count"] or 0)
    observation_count = int(coverage["observation_count"] or 0)

    checkpoints: list[HypothesisCheckpoint] = []
    for hypothesis in hypotheses:
        minimum = int(hypothesis["minimum_independent_dates"])
        if observation_count <= 0:
            state = "NOT_EVALUABLE"
            metrics = {
                "guardrail": "No prospective observations are evaluable.",
                "p_values_enabled": False,
                "fdr_enabled": False,
                "decision_enabled": False,
            }
        elif date_count < minimum:
            state = "INSUFFICIENT_INDEPENDENT_DATES"
            metrics = {
                "minimum_independent_dates": minimum,
                "observed_independent_dates": date_count,
                "guardrail": (
                    "Frozen minimum date count not reached. No hypothesis "
                    "assessment was attempted."
                ),
                "p_values_enabled": False,
                "fdr_enabled": False,
                "decision_enabled": False,
            }
        else:
            state = "DESCRIPTIVE_CHECKPOINT_READY"
            metrics = _metrics_for(
                str(hypothesis["hypothesis_key"]),
                null_run_id=null_run_id,
                db_path=db_path,
            )
            metrics.update(
                {
                    "minimum_independent_dates": minimum,
                    "observed_independent_dates": date_count,
                    "guardrail": (
                        "First frozen prospective descriptive checkpoint. "
                        "No p-values, FDR/BH decision, edge claim, admission "
                        "decision, or automatic model switch is enabled."
                    ),
                    "p_values_enabled": False,
                    "fdr_enabled": False,
                    "decision_enabled": False,
                }
            )

        persisted_id = None
        if persist:
            persisted_id = _persist_checkpoint(
                freeze_run_id=int(freeze["id"]),
                hypothesis=hypothesis,
                coverage=coverage,
                state=state,
                metrics=metrics,
                db_path=db_path,
            )

        checkpoints.append(
            HypothesisCheckpoint(
                hypothesis_key=str(hypothesis["hypothesis_key"]),
                independent_date_count=date_count,
                observation_count=observation_count,
                evaluation_state=state,
                evidence_start_session_date=coverage["first_session_date"],
                evidence_end_session_date=coverage["last_session_date"],
                metrics=metrics,
                persisted_evaluation_id=persisted_id,
            )
        )

    return ProspectiveCheckpointResult(
        freeze_run_id=int(freeze["id"]),
        evaluation_version=EVALUATION_VERSION,
        checkpoints=tuple(checkpoints),
    )


def result_as_dict(result: ProspectiveCheckpointResult) -> dict[str, Any]:
    return {
        "freeze_run_id": result.freeze_run_id,
        "evaluation_version": result.evaluation_version,
        "checkpoints": [asdict(item) for item in result.checkpoints],
        "guardrail": (
            "Descriptive prospective checkpoint only; no trading decision or "
            "edge claim is produced."
        ),
    }
