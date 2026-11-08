from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Sequence

import numpy as np

from src.quant.types import QuantInputError


INCUMBENT_MODEL_ID = "LOCAL_SURFACE_QUADRATIC_V2"
CHALLENGER_MODEL_ID = "NEAREST_BRACKET_LINEAR_V1"
SURFACE_INTELLIGENCE_VERSION = "1.0.0"


@dataclass(frozen=True)
class SurfacePoint:
    strike: float
    implied_volatility: float


@dataclass(frozen=True)
class SurfaceFitObservation:
    strike: float
    actual_iv: float
    incumbent_fitted_iv: float | None
    incumbent_residual: float | None
    incumbent_abs_error: float | None
    challenger_fitted_iv: float | None
    challenger_residual: float | None
    challenger_abs_error: float | None
    incumbent_condition_number: float | None
    state: str
    reason: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class SurfaceTournament:
    version: str
    point_count: int
    evaluable_count: int
    incumbent_model_id: str
    challenger_model_id: str
    incumbent_mae: float | None
    challenger_mae: float | None
    incumbent_rmse: float | None
    challenger_rmse: float | None
    challenger_win_rate: float | None
    median_abs_error_improvement: float | None
    sign_agreement_rate: float | None
    promotion_state: str
    promotion_detail: str
    observations: tuple[SurfaceFitObservation, ...]

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["observations"] = [item.as_dict() for item in self.observations]
        return payload


def _validate(points: Sequence[SurfacePoint]) -> list[SurfacePoint]:
    if len(points) < 5:
        raise QuantInputError("surface comparison requires at least five points")
    ordered = sorted(points, key=lambda item: item.strike)
    strikes = [item.strike for item in ordered]
    if len(set(strikes)) != len(strikes):
        raise QuantInputError("surface strikes must be unique")
    for item in ordered:
        if not math.isfinite(item.strike):
            raise QuantInputError("strike must be finite")
        if not math.isfinite(item.implied_volatility) or item.implied_volatility <= 0:
            raise QuantInputError("implied volatility must be finite and positive")
    return ordered


def _quadratic_loo(target: SurfacePoint, peers: Sequence[SurfacePoint]) -> tuple[float, float]:
    distances = [abs(item.strike - target.strike) for item in peers]
    scale = max(distances)
    if scale <= 0:
        raise QuantInputError("quadratic fit requires distinct strikes")
    z = np.asarray([(item.strike - target.strike) / scale for item in peers], dtype=float)
    y = np.asarray([item.implied_volatility for item in peers], dtype=float)
    design = np.column_stack((z * z, z, np.ones_like(z)))
    coeff, _, rank, _ = np.linalg.lstsq(design, y, rcond=None)
    if int(rank) < 3:
        raise QuantInputError("quadratic fit is rank deficient")
    return float(coeff[2]), float(np.linalg.cond(design))


def _nearest_bracket(target: SurfacePoint, ordered: Sequence[SurfacePoint]) -> float | None:
    lower = [item for item in ordered if item.strike < target.strike]
    upper = [item for item in ordered if item.strike > target.strike]
    if not lower or not upper:
        return None
    left = lower[-1]
    right = upper[0]
    span = right.strike - left.strike
    if span <= 0:
        return None
    weight = (target.strike - left.strike) / span
    return float(left.implied_volatility + weight * (right.implied_volatility - left.implied_volatility))


def compare_surface_models(points: Sequence[SurfacePoint]) -> SurfaceTournament:
    ordered = _validate(points)
    observations: list[SurfaceFitObservation] = []

    for target in ordered:
        peers = [item for item in ordered if item.strike != target.strike]
        challenger = _nearest_bracket(target, ordered)
        try:
            incumbent, condition = _quadratic_loo(target, peers)
        except (QuantInputError, np.linalg.LinAlgError, ValueError, FloatingPointError):
            incumbent = None
            condition = None

        if incumbent is None or challenger is None:
            observations.append(
                SurfaceFitObservation(
                    strike=target.strike,
                    actual_iv=target.implied_volatility,
                    incumbent_fitted_iv=incumbent,
                    incumbent_residual=None if incumbent is None else target.implied_volatility - incumbent,
                    incumbent_abs_error=None if incumbent is None else abs(target.implied_volatility - incumbent),
                    challenger_fitted_iv=challenger,
                    challenger_residual=None if challenger is None else target.implied_volatility - challenger,
                    challenger_abs_error=None if challenger is None else abs(target.implied_volatility - challenger),
                    incumbent_condition_number=condition,
                    state="NOT_COMPARABLE",
                    reason="EDGE_OR_FIT_UNAVAILABLE",
                )
            )
            continue

        incumbent_residual = target.implied_volatility - incumbent
        challenger_residual = target.implied_volatility - challenger
        observations.append(
            SurfaceFitObservation(
                strike=target.strike,
                actual_iv=target.implied_volatility,
                incumbent_fitted_iv=incumbent,
                incumbent_residual=incumbent_residual,
                incumbent_abs_error=abs(incumbent_residual),
                challenger_fitted_iv=challenger,
                challenger_residual=challenger_residual,
                challenger_abs_error=abs(challenger_residual),
                incumbent_condition_number=condition,
                state="COMPARABLE_OBSERVATIONAL",
                reason="LOO_MODELS_COMPARED",
            )
        )

    evaluable = [item for item in observations if item.state == "COMPARABLE_OBSERVATIONAL"]
    if not evaluable:
        return SurfaceTournament(
            version=SURFACE_INTELLIGENCE_VERSION,
            point_count=len(ordered),
            evaluable_count=0,
            incumbent_model_id=INCUMBENT_MODEL_ID,
            challenger_model_id=CHALLENGER_MODEL_ID,
            incumbent_mae=None,
            challenger_mae=None,
            incumbent_rmse=None,
            challenger_rmse=None,
            challenger_win_rate=None,
            median_abs_error_improvement=None,
            sign_agreement_rate=None,
            promotion_state="INSUFFICIENT_EVIDENCE",
            promotion_detail="No comparable leave-one-out observations are available.",
            observations=tuple(observations),
        )

    incumbent_errors = np.asarray([float(item.incumbent_abs_error) for item in evaluable], dtype=float)
    challenger_errors = np.asarray([float(item.challenger_abs_error) for item in evaluable], dtype=float)
    incumbent_residuals = np.asarray([float(item.incumbent_residual) for item in evaluable], dtype=float)
    challenger_residuals = np.asarray([float(item.challenger_residual) for item in evaluable], dtype=float)
    wins = challenger_errors < incumbent_errors
    improvement = incumbent_errors - challenger_errors
    sign_agreement = np.sign(incumbent_residuals) == np.sign(challenger_residuals)

    return SurfaceTournament(
        version=SURFACE_INTELLIGENCE_VERSION,
        point_count=len(ordered),
        evaluable_count=len(evaluable),
        incumbent_model_id=INCUMBENT_MODEL_ID,
        challenger_model_id=CHALLENGER_MODEL_ID,
        incumbent_mae=float(np.mean(incumbent_errors)),
        challenger_mae=float(np.mean(challenger_errors)),
        incumbent_rmse=float(np.sqrt(np.mean(incumbent_errors**2))),
        challenger_rmse=float(np.sqrt(np.mean(challenger_errors**2))),
        challenger_win_rate=float(np.mean(wins)),
        median_abs_error_improvement=float(np.median(improvement)),
        sign_agreement_rate=float(np.mean(sign_agreement)),
        promotion_state="RESEARCH_ONLY_CHALLENGER",
        promotion_detail=(
            "This comparison is observational only. The frozen incumbent remains authoritative; "
            "the challenger requires prospective multi-date evidence before any promotion review."
        ),
        observations=tuple(observations),
    )
