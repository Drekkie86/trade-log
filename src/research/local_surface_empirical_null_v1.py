from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import numpy as np

from src.database.repository import get_connection

UTC = ZoneInfo("UTC")

NULL_FAMILY_ID = "LOCAL_SURFACE_EMPIRICAL_NULL_V1"
NULL_MODEL_VERSION = "0.1.0"
STRATIFICATION_VERSION = "RIGHT_DTE_ABSDELTA_V1"
DEPENDENCE_SPEC_VERSION = "REPEATED_CLUSTER_ICC_PROXY_V1"
SOURCE_V2_MODEL_VERSION = "0.1.0"
ROBUST_SCALE_FACTOR = 1.4826
CELL_PRIOR_STRENGTH = 50.0
RIGHT_PRIOR_STRENGTH = 100.0
MIN_GLOBAL_OBSERVATIONS = 100


class LocalSurfaceEmpiricalNullError(RuntimeError):
    pass


@dataclass(frozen=True)
class DiscoveryWindow:
    window_id: str
    start: str
    end: str


@dataclass(frozen=True)
class NullSourceObservation:
    observation_id: int
    research_run_id: int
    session_date: str
    underlying: str
    expiration: str
    strike: float
    right: str
    abs_delta: float
    dte: int
    spread_to_mid: float | None
    loo_residual: float


@dataclass(frozen=True)
class StratumEstimate:
    stratum_key: str
    right: str
    dte_bucket: str
    abs_delta_bucket: str
    observation_count: int
    raw_mean: float
    raw_std: float
    raw_median: float
    raw_mad: float
    raw_robust_scale: float
    q01: float
    q025: float
    q05: float
    q50: float
    q95: float
    q975: float
    q99: float
    parent_observation_count: int
    parent_location: float
    parent_scale: float
    shrinkage_weight: float
    shrunk_location: float
    shrunk_scale: float


@dataclass(frozen=True)
class DependenceEstimate:
    cluster_dimension: str
    raw_observation_count: int
    cluster_count: int
    repeated_cluster_count: int
    mean_cluster_size: float
    median_cluster_size: float
    max_cluster_size: int
    cluster_size_cv: float
    icc_oneway: float | None
    design_effect_proxy: float | None
    effective_n_proxy: float | None
    estimator_state: str


@dataclass(frozen=True)
class EmpiricalNullFitResult:
    null_run_id: int | None
    source_first_session_date: str
    source_last_session_date: str
    source_max_observation_id: int
    observation_count: int
    stratum_count: int
    discovery_window_count: int
    strata: tuple[StratumEstimate, ...]
    dependence: tuple[DependenceEstimate, ...]


def _registry_path(repo_root: Path | None = None) -> Path:
    if repo_root is not None:
        return Path(repo_root) / "research" / "edge_discovery" / "DISCOVERY_WINDOW_REGISTRY.json"
    return Path(__file__).resolve().parents[2] / "research" / "edge_discovery" / "DISCOVERY_WINDOW_REGISTRY.json"


def load_discovery_windows(repo_root: Path | None = None) -> tuple[DiscoveryWindow, ...]:
    path = _registry_path(repo_root)
    payload = json.loads(path.read_text(encoding="utf-8"))
    windows = []
    for item in payload.get("discovery_windows", []):
        start = str(item["start"])
        end = str(item["end"])
        if end < start:
            raise LocalSurfaceEmpiricalNullError(f"Discovery window ends before it starts: {item}")
        windows.append(DiscoveryWindow(str(item["window_id"]), start, end))
    if not windows:
        raise LocalSurfaceEmpiricalNullError("Discovery-window registry contains no windows.")
    return tuple(windows)


def _date_is_discovery(date: str, windows: Iterable[DiscoveryWindow]) -> bool:
    return any(item.start <= date <= item.end for item in windows)


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


def _delta_bucket(abs_delta: float) -> str:
    if 0.10 <= abs_delta < 0.25:
        return "ABSDELTA_10_25"
    if 0.25 <= abs_delta < 0.40:
        return "ABSDELTA_25_40"
    if 0.40 <= abs_delta < 0.60:
        return "ABSDELTA_40_60"
    if 0.60 <= abs_delta <= 0.80:
        return "ABSDELTA_60_80"
    return "ABSDELTA_OTHER"


def _stratum_key(item: NullSourceObservation) -> str:
    return f"{item.right}|{_dte_bucket(item.dte)}|{_delta_bucket(item.abs_delta)}"


def _robust_summary(values: list[float]) -> dict[str, float]:
    if not values:
        raise LocalSurfaceEmpiricalNullError("Cannot summarize an empty residual set.")
    arr = np.asarray(values, dtype=float)
    raw_mean = float(np.mean(arr))
    raw_std = float(np.std(arr, ddof=1)) if len(arr) > 1 else 0.0
    med = float(np.median(arr))
    mad = float(np.median(np.abs(arr - med)))
    robust_scale = ROBUST_SCALE_FACTOR * mad
    if robust_scale <= 0.0 and raw_std > 0.0:
        robust_scale = raw_std
    quantiles = np.quantile(arr, [0.01, 0.025, 0.05, 0.50, 0.95, 0.975, 0.99], method="linear")
    return {
        "raw_mean": raw_mean,
        "raw_std": raw_std,
        "raw_median": med,
        "raw_mad": mad,
        "raw_robust_scale": float(robust_scale),
        "q01": float(quantiles[0]),
        "q025": float(quantiles[1]),
        "q05": float(quantiles[2]),
        "q50": float(quantiles[3]),
        "q95": float(quantiles[4]),
        "q975": float(quantiles[5]),
        "q99": float(quantiles[6]),
    }


def _blend(value: float, parent: float, n: int, prior_strength: float) -> tuple[float, float]:
    weight = float(n) / (float(n) + float(prior_strength))
    return weight * value + (1.0 - weight) * parent, weight


def estimate_strata(observations: Iterable[NullSourceObservation]) -> tuple[StratumEstimate, ...]:
    items = list(observations)
    if len(items) < MIN_GLOBAL_OBSERVATIONS:
        raise LocalSurfaceEmpiricalNullError(
            f"Empirical null requires at least {MIN_GLOBAL_OBSERVATIONS} discovery observations; found {len(items)}."
        )

    global_stats = _robust_summary([item.loo_residual for item in items])
    by_right: dict[str, list[NullSourceObservation]] = defaultdict(list)
    by_cell: dict[str, list[NullSourceObservation]] = defaultdict(list)
    for item in items:
        by_right[item.right].append(item)
        by_cell[_stratum_key(item)].append(item)

    right_parent: dict[str, tuple[int, float, float]] = {}
    for right, rows in by_right.items():
        stats = _robust_summary([item.loo_residual for item in rows])
        location, _ = _blend(stats["raw_median"], global_stats["raw_median"], len(rows), RIGHT_PRIOR_STRENGTH)
        scale, _ = _blend(stats["raw_robust_scale"], global_stats["raw_robust_scale"], len(rows), RIGHT_PRIOR_STRENGTH)
        right_parent[right] = (len(rows), location, max(scale, 0.0))

    result = []
    for key in sorted(by_cell):
        rows = by_cell[key]
        first = rows[0]
        stats = _robust_summary([item.loo_residual for item in rows])
        parent_n, parent_location, parent_scale = right_parent[first.right]
        shrunk_location, weight = _blend(stats["raw_median"], parent_location, len(rows), CELL_PRIOR_STRENGTH)
        shrunk_scale, _ = _blend(stats["raw_robust_scale"], parent_scale, len(rows), CELL_PRIOR_STRENGTH)
        result.append(
            StratumEstimate(
                stratum_key=key,
                right=first.right,
                dte_bucket=_dte_bucket(first.dte),
                abs_delta_bucket=_delta_bucket(first.abs_delta),
                observation_count=len(rows),
                parent_observation_count=parent_n,
                parent_location=parent_location,
                parent_scale=parent_scale,
                shrinkage_weight=weight,
                shrunk_location=shrunk_location,
                shrunk_scale=max(shrunk_scale, 0.0),
                **stats,
            )
        )
    return tuple(result)


def _icc_oneway(groups: list[list[float]]) -> float | None:
    groups = [group for group in groups if group]
    n_total = sum(len(group) for group in groups)
    k = len(groups)
    if k < 2 or n_total <= k:
        return None
    grand = sum(sum(group) for group in groups) / n_total
    ss_between = sum(len(group) * (sum(group) / len(group) - grand) ** 2 for group in groups)
    ss_within = sum(sum((value - sum(group) / len(group)) ** 2 for value in group) for group in groups)
    ms_between = ss_between / (k - 1)
    ms_within = ss_within / (n_total - k)
    n0 = (n_total - sum(len(group) ** 2 for group in groups) / n_total) / (k - 1)
    denominator = ms_between + (n0 - 1.0) * ms_within
    if n0 <= 0 or denominator <= 0:
        return None
    return float((ms_between - ms_within) / denominator)


def _cluster_key(item: NullSourceObservation, dimension: str) -> str:
    if dimension == "CONTRACT_SESSION":
        return f"{item.underlying}|{item.expiration}|{item.strike:.8f}|{item.right}|{item.session_date}"
    if dimension == "SURFACE_SESSION":
        return f"{item.underlying}|{item.expiration}|{item.right}|{item.session_date}"
    if dimension == "UNDERLYING_SESSION":
        return f"{item.underlying}|{item.session_date}"
    if dimension == "SESSION_DATE":
        return item.session_date
    raise ValueError(f"Unknown cluster dimension: {dimension}")


def estimate_dependence(observations: Iterable[NullSourceObservation]) -> tuple[DependenceEstimate, ...]:
    items = list(observations)
    if not items:
        raise LocalSurfaceEmpiricalNullError("No observations available for dependence diagnostics.")
    result = []
    for dimension in ("CONTRACT_SESSION", "SURFACE_SESSION", "UNDERLYING_SESSION", "SESSION_DATE"):
        clustered: dict[str, list[float]] = defaultdict(list)
        for item in items:
            clustered[_cluster_key(item, dimension)].append(item.loo_residual)
        sizes = [len(values) for values in clustered.values()]
        repeated = [values for values in clustered.values() if len(values) >= 2]
        mean_size = float(np.mean(sizes))
        median_size = float(np.median(sizes))
        std_size = float(np.std(sizes, ddof=0))
        cv = std_size / mean_size if mean_size > 0 else 0.0
        icc = _icc_oneway(repeated)
        if icc is None:
            state = "INSUFFICIENT_REPEATED_CLUSTERS"
            design_effect = None
            effective_n = None
        else:
            rho = max(icc, 0.0)
            # Unequal-cluster-size exploratory design-effect approximation.
            design_effect = 1.0 + (((cv * cv + 1.0) * mean_size) - 1.0) * rho
            design_effect = max(float(design_effect), 1.0)
            effective_n = float(len(items)) / design_effect
            state = "ESTIMATED_EXPLORATORY"
        result.append(
            DependenceEstimate(
                cluster_dimension=dimension,
                raw_observation_count=len(items),
                cluster_count=len(clustered),
                repeated_cluster_count=len(repeated),
                mean_cluster_size=mean_size,
                median_cluster_size=median_size,
                max_cluster_size=max(sizes),
                cluster_size_cv=cv,
                icc_oneway=icc,
                design_effect_proxy=design_effect,
                effective_n_proxy=effective_n,
                estimator_state=state,
            )
        )
    return tuple(result)


def _load_source_observations(*, windows: tuple[DiscoveryWindow, ...], db_path=None) -> list[NullSourceObservation]:
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            """
            SELECT
                v2.observation_id,
                v2.research_run_id,
                v2.us_session_date,
                v2.underlying,
                v2.expiration,
                v2.strike,
                v2.right,
                v2.abs_delta,
                v2.dte,
                v2.spread_to_mid,
                v2.loo_residual
            FROM v_local_surface_residual_v2_discovery_dataset AS v2
            WHERE v2.model_version = ?
              AND v2.observation_state = 'EVALUATED_OBSERVATIONAL'
              AND v2.loo_residual IS NOT NULL
              AND v2.abs_delta IS NOT NULL
              AND v2.dte IS NOT NULL
            ORDER BY v2.observation_id;
            """
        ,
            (SOURCE_V2_MODEL_VERSION,),
        ).fetchall()
    finally:
        conn.close()
    result = []
    for row in rows:
        session_date = str(row["us_session_date"])
        if not _date_is_discovery(session_date, windows):
            continue
        result.append(
            NullSourceObservation(
                observation_id=int(row["observation_id"]),
                research_run_id=int(row["research_run_id"]),
                session_date=session_date,
                underlying=str(row["underlying"]),
                expiration=str(row["expiration"]),
                strike=float(row["strike"]),
                right=str(row["right"]),
                abs_delta=float(row["abs_delta"]),
                dte=int(row["dte"]),
                spread_to_mid=None if row["spread_to_mid"] is None else float(row["spread_to_mid"]),
                loo_residual=float(row["loo_residual"]),
            )
        )
    return result


def _config(windows: tuple[DiscoveryWindow, ...]) -> dict[str, Any]:
    return {
        "null_family_id": NULL_FAMILY_ID,
        "null_model_version": NULL_MODEL_VERSION,
        "stratification_version": STRATIFICATION_VERSION,
        "dependence_spec_version": DEPENDENCE_SPEC_VERSION,
        "source_v2_model_version": SOURCE_V2_MODEL_VERSION,
        "discovery_windows": [asdict(item) for item in windows],
        "cell_prior_strength": CELL_PRIOR_STRENGTH,
        "right_prior_strength": RIGHT_PRIOR_STRENGTH,
        "robust_scale_factor": ROBUST_SCALE_FACTOR,
        "minimum_global_observations": MIN_GLOBAL_OBSERVATIONS,
        "p_values_enabled": False,
        "fdr_enabled": False,
        "decision_enabled": False,
        "candidate_creation": False,
        "edge_claim": False,
    }


def _hash_config(config: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(config, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def fit_empirical_null_v1(*, repo_root: Path | None = None, persist: bool = True, db_path=None) -> EmpiricalNullFitResult:
    windows = load_discovery_windows(repo_root)
    observations = _load_source_observations(windows=windows, db_path=db_path)
    if len(observations) < MIN_GLOBAL_OBSERVATIONS:
        raise LocalSurfaceEmpiricalNullError(
            f"Only {len(observations)} eligible V2 discovery observations are available; need {MIN_GLOBAL_OBSERVATIONS}."
        )
    strata = estimate_strata(observations)
    dependence = estimate_dependence(observations)
    source_first = min(item.session_date for item in observations)
    source_last = max(item.session_date for item in observations)
    source_max = max(item.observation_id for item in observations)
    config = _config(windows)
    config_hash = _hash_config(config)

    if not persist:
        return EmpiricalNullFitResult(
            null_run_id=None,
            source_first_session_date=source_first,
            source_last_session_date=source_last,
            source_max_observation_id=source_max,
            observation_count=len(observations),
            stratum_count=len(strata),
            discovery_window_count=len(windows),
            strata=strata,
            dependence=dependence,
        )

    fitted_at = datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    conn = get_connection(db_path)
    try:
        with conn:
            existing = conn.execute(
                """
                SELECT id FROM local_surface_null_v1_runs
                WHERE null_model_version = ? AND config_hash = ? AND source_max_observation_id = ?;
                """,
                (NULL_MODEL_VERSION, config_hash, source_max),
            ).fetchone()
            if existing is not None:
                raise LocalSurfaceEmpiricalNullError(
                    f"Empirical null already persisted for this discovery dataset: null_run_id={int(existing['id'])}."
                )
            cursor = conn.execute(
                """
                INSERT INTO local_surface_null_v1_runs (
                    null_family_id, null_model_version, stratification_version,
                    dependence_spec_version, source_v2_model_version, config_hash,
                    config_json, fitted_at, source_first_session_date, source_last_session_date,
                    source_max_observation_id, observation_count, stratum_count,
                    discovery_window_count, model_state, p_values_enabled, fdr_enabled, decision_enabled
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ESTIMATED_DISCOVERY_ONLY', 0, 0, 0);
                """,
                (
                    NULL_FAMILY_ID, NULL_MODEL_VERSION, STRATIFICATION_VERSION,
                    DEPENDENCE_SPEC_VERSION, SOURCE_V2_MODEL_VERSION, config_hash,
                    json.dumps(config, sort_keys=True, separators=(",", ":")), fitted_at,
                    source_first, source_last, source_max, len(observations), len(strata), len(windows),
                ),
            )
            null_run_id = int(cursor.lastrowid)
            stratum_ids: dict[str, int] = {}
            for item in strata:
                c = conn.execute(
                    """
                    INSERT INTO local_surface_null_v1_strata (
                        null_run_id, stratum_key, right, dte_bucket, abs_delta_bucket,
                        observation_count, raw_mean, raw_std, raw_median, raw_mad,
                        raw_robust_scale, q01, q025, q05, q50, q95, q975, q99,
                        parent_observation_count, parent_location, parent_scale,
                        shrinkage_weight, shrunk_location, shrunk_scale
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (null_run_id, *asdict(item).values()),
                )
                stratum_ids[item.stratum_key] = int(c.lastrowid)
            stratum_by_key = {item.stratum_key: item for item in strata}
            conn.executemany(
                """
                INSERT INTO local_surface_null_v1_membership (
                    null_run_id, v2_observation_id, stratum_id, session_date,
                    loo_residual, centered_residual, abs_centered_residual
                ) VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    (
                        null_run_id,
                        item.observation_id,
                        stratum_ids[_stratum_key(item)],
                        item.session_date,
                        item.loo_residual,
                        item.loo_residual - stratum_by_key[_stratum_key(item)].shrunk_location,
                        abs(item.loo_residual - stratum_by_key[_stratum_key(item)].shrunk_location),
                    )
                    for item in observations
                ),
            )
            conn.executemany(
                """
                INSERT INTO local_surface_null_v1_dependence (
                    null_run_id, cluster_dimension, raw_observation_count, cluster_count,
                    repeated_cluster_count, mean_cluster_size, median_cluster_size,
                    max_cluster_size, cluster_size_cv, icc_oneway, design_effect_proxy,
                    effective_n_proxy, estimator_state
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                ((null_run_id, *asdict(item).values()) for item in dependence),
            )
    finally:
        conn.close()

    return EmpiricalNullFitResult(
        null_run_id=null_run_id,
        source_first_session_date=source_first,
        source_last_session_date=source_last,
        source_max_observation_id=source_max,
        observation_count=len(observations),
        stratum_count=len(strata),
        discovery_window_count=len(windows),
        strata=strata,
        dependence=dependence,
    )
