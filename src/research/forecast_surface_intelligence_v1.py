from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Sequence

from src.quant.forecast_validation import (
    ForecastObservation,
    ForecastTournament,
    summarize_by_regime,
    tournament,
)
from src.research.surface_intelligence_v1 import (
    SurfacePoint,
    SurfaceTournament,
    compare_surface_models,
)


FORECAST_SURFACE_PACKAGE_VERSION = "1.0.0"


@dataclass(frozen=True)
class ForecastSurfaceIntelligence:
    version: str
    forecast_tournament: ForecastTournament
    regime_tournaments: dict[str, ForecastTournament]
    surface_tournament: SurfaceTournament
    decision_authority: str
    readiness_state: str
    readiness_detail: str

    def as_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "forecast_tournament": self.forecast_tournament.as_dict(),
            "regime_tournaments": {
                regime: result.as_dict()
                for regime, result in self.regime_tournaments.items()
            },
            "surface_tournament": self.surface_tournament.as_dict(),
            "decision_authority": self.decision_authority,
            "readiness_state": self.readiness_state,
            "readiness_detail": self.readiness_detail,
        }


def build_forecast_surface_intelligence(
    forecast_observations: Sequence[ForecastObservation],
    surface_points: Sequence[SurfacePoint],
    *,
    scoring_rule: str = "QLIKE",
    expected_interval_coverage: float | None = None,
    bootstrap_samples: int = 2000,
    confidence: float = 0.95,
    seed: int = 17,
) -> ForecastSurfaceIntelligence:
    forecast_result = tournament(
        forecast_observations,
        scoring_rule=scoring_rule,
        expected_interval_coverage=expected_interval_coverage,
        bootstrap_samples=bootstrap_samples,
        confidence=confidence,
        seed=seed,
    )
    regimes = dict(
        summarize_by_regime(
            forecast_observations,
            expected_interval_coverage=expected_interval_coverage,
            bootstrap_samples=bootstrap_samples,
            confidence=confidence,
            seed=seed + 1000,
        )
    )
    surface_result = compare_surface_models(surface_points)

    if forecast_result.comparable_model_count < 2:
        readiness_state = "ACCUMULATING_FORECAST_COMPARISON"
        readiness_detail = (
            "At least two forecast models need comparable observations before a forecast tournament is meaningful."
        )
    elif surface_result.evaluable_count < 3:
        readiness_state = "ACCUMULATING_SURFACE_COMPARISON"
        readiness_detail = (
            "Forecast models are comparable, but the surface challenger still has too few comparable interior points."
        )
    else:
        readiness_state = "RESEARCH_COMPARISON_READY"
        readiness_detail = (
            "Forecast and surface comparisons are available for research review. This is not trading or model-promotion authority."
        )

    return ForecastSurfaceIntelligence(
        version=FORECAST_SURFACE_PACKAGE_VERSION,
        forecast_tournament=forecast_result,
        regime_tournaments=regimes,
        surface_tournament=surface_result,
        decision_authority="NONE_RESEARCH_ONLY",
        readiness_state=readiness_state,
        readiness_detail=readiness_detail,
    )
