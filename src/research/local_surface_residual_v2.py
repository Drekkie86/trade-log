from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np

from src.database.repository import get_connection
from src.research.deterministic_scanner import ScannerObservation, ScannerRunSummary, scan_research_run

UTC = ZoneInfo("UTC")

MODEL_FAMILY_ID = "LOCAL_SURFACE_RESIDUAL_V2"
MODEL_VERSION = "0.1.0"
FIT_SPEC_VERSION = "LOO_QUADRATIC_CENTERED_V1"
DEFAULT_MIN_ABS_DELTA = 0.10
DEFAULT_MAX_ABS_DELTA = 0.80
MIN_USABLE_STRIKES = 5


class LocalSurfaceResidualV2Error(RuntimeError):
    pass


@dataclass(frozen=True)
class SurfaceResidualObservation:
    reference_contract_id: int
    option_quote_id: int
    underlying: str
    expiration: str
    strike: float
    right: str
    delta: float | None
    implied_volatility: float | None
    usable_strike_count: int
    fit_point_count: int | None
    fit_dof: int | None
    fitted_iv: float | None
    loo_residual: float | None
    abs_loo_residual: float | None
    fit_sse: float | None
    fit_rmse: float | None
    design_condition_number: float | None
    observation_state: str
    reason_code: str


@dataclass(frozen=True)
class LocalSurfaceResidualV2Result:
    research_run_id: int
    model_family_id: str
    model_version: str
    fit_spec_version: str
    config_hash: str
    structural_input_count: int
    reference_mapped_count: int
    evaluable_count: int
    observations: tuple[SurfaceResidualObservation, ...]
    persisted_model_run_id: int | None


def _config(*, max_spread_to_mid: float, min_abs_delta: float, max_abs_delta: float) -> dict[str, Any]:
    if not (0 <= min_abs_delta < max_abs_delta <= 1):
        raise ValueError("Delta band must satisfy 0 <= min < max <= 1.")
    return {
        "model_family_id": MODEL_FAMILY_ID,
        "model_version": MODEL_VERSION,
        "fit_spec_version": FIT_SPEC_VERSION,
        "max_spread_to_mid": float(max_spread_to_mid),
        "min_abs_delta": float(min_abs_delta),
        "max_abs_delta": float(max_abs_delta),
        "min_usable_strikes": MIN_USABLE_STRIKES,
        "surface_classification": False,
        "candidate_creation": False,
        "edge_claim": False,
        "p_values": False,
    }


def _hash_config(config: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(config, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _load_reference_and_iv(*, research_run_id: int, option_quote_ids: list[int], db_path=None) -> dict[int, dict[str, Any]]:
    if not option_quote_ids:
        return {}
    conn = get_connection(db_path)
    try:
        conn.execute("CREATE TEMP TABLE _surface_v2_target_quote_ids (id INTEGER PRIMARY KEY);")
        conn.executemany(
            "INSERT INTO _surface_v2_target_quote_ids (id) VALUES (?);",
            ((quote_id,) for quote_id in option_quote_ids),
        )
        rows = conn.execute(
            """
            SELECT
                oq.id AS option_quote_id,
                lrc.id AS reference_contract_id,
                pmo.implied_volatility
            FROM _surface_v2_target_quote_ids AS target
            JOIN option_quotes AS oq ON oq.id = target.id
            JOIN market_snapshots AS ms ON ms.id = oq.snapshot_id
            JOIN listing_reference_contracts AS lrc
              ON lrc.research_run_id = ms.research_run_id
             AND lrc.provider = 'MASSIVE'
             AND lrc.underlying = ms.underlying
             AND lrc.expiration = oq.expiration
             AND lrc.strike = oq.strike
             AND lrc.right = oq.right
            LEFT JOIN provider_model_observations AS pmo
              ON pmo.option_quote_id = oq.id
             AND pmo.provider = 'THETADATA'
            WHERE ms.research_run_id = ?;
            """,
            (research_run_id,),
        ).fetchall()
    finally:
        try:
            conn.execute("DROP TABLE IF EXISTS _surface_v2_target_quote_ids;")
        finally:
            conn.close()

    result: dict[int, dict[str, Any]] = {}
    for row in rows:
        quote_id = int(row["option_quote_id"])
        if quote_id in result:
            raise LocalSurfaceResidualV2Error(
                f"Ambiguous canonical reference/model join for option_quote_id={quote_id}."
            )
        result[quote_id] = {
            "reference_contract_id": int(row["reference_contract_id"]),
            "implied_volatility": None if row["implied_volatility"] is None else float(row["implied_volatility"]),
        }
    return result


def _fit_loo(target: ScannerObservation, peers: list[tuple[ScannerObservation, int, float]]) -> tuple[float, float, float, float, int]:
    # Center and scale strikes around the omitted target. This keeps the
    # polynomial numerically stable while preserving fitted_iv at z=0.
    distances = [abs(item[0].strike - target.strike) for item in peers]
    scale = max(distances)
    if scale <= 0:
        raise LocalSurfaceResidualV2Error("LOO fit requires distinct strikes.")

    z = np.asarray([(item[0].strike - target.strike) / scale for item in peers], dtype=float)
    y = np.asarray([item[2] for item in peers], dtype=float)
    design = np.column_stack((z * z, z, np.ones_like(z)))
    coeff, _residuals, rank, _singular = np.linalg.lstsq(design, y, rcond=None)
    if int(rank) < 3:
        raise LocalSurfaceResidualV2Error("LOO quadratic design is rank deficient.")

    fitted_values = design @ coeff
    errors = y - fitted_values
    sse = float(errors @ errors)
    dof = len(peers) - 3
    rmse = math.sqrt(sse / dof) if dof > 0 else math.nan
    fitted_target = float(coeff[2])
    condition = float(np.linalg.cond(design))
    return fitted_target, sse, rmse, condition, dof


def _evaluate_group(
    observations: list[tuple[ScannerObservation, int, float | None]],
    *,
    min_abs_delta: float,
    max_abs_delta: float,
) -> list[SurfaceResidualObservation]:
    ordered = sorted(observations, key=lambda item: item[0].strike)
    usable = [
        item
        for item in ordered
        if item[0].delta is not None
        and item[2] is not None
        and min_abs_delta <= abs(float(item[0].delta)) <= max_abs_delta
    ]
    usable_count = len(usable)
    usable_quote_ids = {item[0].option_quote_id for item in usable}
    results: list[SurfaceResidualObservation] = []

    for observation, reference_id, iv in ordered:
        delta = observation.delta
        common = dict(
            reference_contract_id=reference_id,
            option_quote_id=observation.option_quote_id,
            underlying=observation.underlying,
            expiration=observation.expiration,
            strike=observation.strike,
            right=observation.right,
            delta=delta,
            implied_volatility=iv,
            usable_strike_count=usable_count,
        )
        if delta is None:
            results.append(SurfaceResidualObservation(**common, fit_point_count=None, fit_dof=None, fitted_iv=None, loo_residual=None, abs_loo_residual=None, fit_sse=None, fit_rmse=None, design_condition_number=None, observation_state="NOT_EVALUABLE", reason_code="DELTA_MISSING"))
            continue
        if not (min_abs_delta <= abs(delta) <= max_abs_delta):
            results.append(SurfaceResidualObservation(**common, fit_point_count=None, fit_dof=None, fitted_iv=None, loo_residual=None, abs_loo_residual=None, fit_sse=None, fit_rmse=None, design_condition_number=None, observation_state="NOT_EVALUABLE", reason_code="DELTA_OUT_OF_BAND"))
            continue
        if iv is None:
            results.append(SurfaceResidualObservation(**common, fit_point_count=None, fit_dof=None, fitted_iv=None, loo_residual=None, abs_loo_residual=None, fit_sse=None, fit_rmse=None, design_condition_number=None, observation_state="NOT_EVALUABLE", reason_code="IV_MISSING"))
            continue
        if observation.option_quote_id not in usable_quote_ids or usable_count < MIN_USABLE_STRIKES:
            results.append(SurfaceResidualObservation(**common, fit_point_count=max(usable_count - 1, 0), fit_dof=max(usable_count - 4, 0), fitted_iv=None, loo_residual=None, abs_loo_residual=None, fit_sse=None, fit_rmse=None, design_condition_number=None, observation_state="NOT_EVALUABLE", reason_code="INSUFFICIENT_USABLE_STRIKES"))
            continue

        peers = [item for item in usable if item[0].option_quote_id != observation.option_quote_id]
        try:
            fitted, sse, rmse, condition, dof = _fit_loo(observation, [(o, r, float(v)) for o, r, v in peers if v is not None])
        except (LocalSurfaceResidualV2Error, np.linalg.LinAlgError, ValueError, FloatingPointError):
            results.append(SurfaceResidualObservation(**common, fit_point_count=len(peers), fit_dof=max(len(peers) - 3, 0), fitted_iv=None, loo_residual=None, abs_loo_residual=None, fit_sse=None, fit_rmse=None, design_condition_number=None, observation_state="NOT_EVALUABLE", reason_code="FIT_FAILED"))
            continue

        residual = float(iv) - fitted
        results.append(
            SurfaceResidualObservation(
                **common,
                fit_point_count=len(peers),
                fit_dof=dof,
                fitted_iv=fitted,
                loo_residual=residual,
                abs_loo_residual=abs(residual),
                fit_sse=sse,
                fit_rmse=rmse,
                design_condition_number=condition,
                observation_state="EVALUATED_OBSERVATIONAL",
                reason_code="LOO_QUADRATIC_RESIDUAL_MEASURED",
            )
        )
    return results


def _persist(
    *,
    research_run_id: int,
    config: dict[str, Any],
    observations: list[SurfaceResidualObservation],
    structural_input_count: int,
    reference_mapped_count: int,
    db_path=None,
) -> int:
    observed_at = datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    evaluable_count = sum(item.observation_state == "EVALUATED_OBSERVATIONAL" for item in observations)
    conn = get_connection(db_path)
    try:
        with conn:
            existing = conn.execute(
                "SELECT id FROM local_surface_residual_v2_runs WHERE research_run_id = ? AND model_version = ?;",
                (research_run_id, MODEL_VERSION),
            ).fetchone()
            if existing is not None:
                raise LocalSurfaceResidualV2Error(
                    f"V2 observations already persisted for research_run_id={research_run_id}, model_version={MODEL_VERSION}."
                )
            cursor = conn.execute(
                """
                INSERT INTO local_surface_residual_v2_runs (
                    research_run_id, model_family_id, model_version, fit_spec_version,
                    config_hash, config_json, observed_at, structural_input_count,
                    reference_mapped_count, evaluable_count, surfaced_count, decision_enabled
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0);
                """,
                (
                    research_run_id, MODEL_FAMILY_ID, MODEL_VERSION, FIT_SPEC_VERSION,
                    _hash_config(config), json.dumps(config, sort_keys=True, separators=(",", ":")),
                    observed_at, structural_input_count, reference_mapped_count, evaluable_count,
                ),
            )
            run_id = int(cursor.lastrowid)
            conn.executemany(
                """
                INSERT INTO local_surface_residual_v2_observations (
                    model_run_id, reference_contract_id, option_quote_id, underlying,
                    expiration, strike, right, delta, implied_volatility,
                    usable_strike_count, fit_point_count, fit_dof, fitted_iv,
                    loo_residual, abs_loo_residual, fit_sse, fit_rmse,
                    design_condition_number, observation_state, reason_code, evidence_json
                ) VALUES (
                    :model_run_id, :reference_contract_id, :option_quote_id, :underlying,
                    :expiration, :strike, :right, :delta, :implied_volatility,
                    :usable_strike_count, :fit_point_count, :fit_dof, :fitted_iv,
                    :loo_residual, :abs_loo_residual, :fit_sse, :fit_rmse,
                    :design_condition_number, :observation_state, :reason_code, :evidence_json
                );
                """,
                [
                    {
                        "model_run_id": run_id,
                        **asdict(item),
                        "evidence_json": json.dumps(
                            {
                                "model_family_id": MODEL_FAMILY_ID,
                                "model_version": MODEL_VERSION,
                                "fit_spec_version": FIT_SPEC_VERSION,
                                "surface_classification": False,
                                "p_value": None,
                                "fdr_decision": None,
                            },
                            sort_keys=True,
                        ),
                    }
                    for item in observations
                ],
            )
        return run_id
    finally:
        conn.close()


def scan_local_surface_residual_v2(
    *,
    research_run_id: int,
    max_spread_to_mid: float = 0.20,
    min_abs_delta: float = DEFAULT_MIN_ABS_DELTA,
    max_abs_delta: float = DEFAULT_MAX_ABS_DELTA,
    persist: bool = True,
    structural_summary: ScannerRunSummary | None = None,
    db_path=None,
) -> LocalSurfaceResidualV2Result:
    structural = structural_summary if structural_summary is not None else scan_research_run(
        research_run_id=research_run_id,
        max_spread_to_mid=max_spread_to_mid,
        db_path=db_path,
    )
    eligible = [item for item in structural.observations if item.structurally_eligible]
    config = _config(max_spread_to_mid=max_spread_to_mid, min_abs_delta=min_abs_delta, max_abs_delta=max_abs_delta)
    metadata = _load_reference_and_iv(
        research_run_id=research_run_id,
        option_quote_ids=[item.option_quote_id for item in eligible],
        db_path=db_path,
    )
    groups: dict[tuple[str, str, str], list[tuple[ScannerObservation, int, float | None]]] = {}
    for item in eligible:
        detail = metadata.get(item.option_quote_id)
        if detail is None:
            continue
        groups.setdefault((item.underlying, item.expiration, item.right), []).append(
            (item, detail["reference_contract_id"], detail["implied_volatility"])
        )

    observations: list[SurfaceResidualObservation] = []
    for group in groups.values():
        observations.extend(_evaluate_group(group, min_abs_delta=min_abs_delta, max_abs_delta=max_abs_delta))
    observations.sort(key=lambda item: (item.underlying, item.expiration, item.right, item.strike))

    persisted_id = None
    if persist:
        persisted_id = _persist(
            research_run_id=research_run_id,
            config=config,
            observations=observations,
            structural_input_count=len(eligible),
            reference_mapped_count=len(metadata),
            db_path=db_path,
        )
    return LocalSurfaceResidualV2Result(
        research_run_id=research_run_id,
        model_family_id=MODEL_FAMILY_ID,
        model_version=MODEL_VERSION,
        fit_spec_version=FIT_SPEC_VERSION,
        config_hash=_hash_config(config),
        structural_input_count=len(eligible),
        reference_mapped_count=len(metadata),
        evaluable_count=sum(item.observation_state == "EVALUATED_OBSERVATIONAL" for item in observations),
        observations=tuple(observations),
        persisted_model_run_id=persisted_id,
    )
