from src.quant.forecast_validation import ForecastObservation
from src.research.forecast_surface_intelligence_v1 import build_forecast_surface_intelligence
from src.research.surface_intelligence_v1 import SurfacePoint


def test_composite_package_is_research_only_and_ready_when_both_comparisons_exist() -> None:
    forecasts = []
    for realized in (0.03, 0.04, 0.05, 0.06):
        forecasts.append(ForecastObservation("EWMA", realized * 1.02, realized, 5, "CALM"))
        forecasts.append(ForecastObservation("GARCH11", realized * 1.10, realized, 5, "CALM"))

    surface = [
        SurfacePoint(90, 0.30),
        SurfacePoint(95, 0.26),
        SurfacePoint(100, 0.24),
        SurfacePoint(105, 0.25),
        SurfacePoint(110, 0.29),
    ]

    result = build_forecast_surface_intelligence(
        forecasts,
        surface,
        bootstrap_samples=50,
    )

    assert result.decision_authority == "NONE_RESEARCH_ONLY"
    assert result.readiness_state == "RESEARCH_COMPARISON_READY"
    assert result.forecast_tournament.comparable_model_count == 2
    assert result.surface_tournament.evaluable_count == 3
    assert "CALM" in result.regime_tournaments


def test_composite_package_waits_for_two_forecast_models() -> None:
    forecasts = [
        ForecastObservation("EWMA", 0.04, 0.04, 5, "CALM"),
        ForecastObservation("EWMA", 0.05, 0.05, 5, "CALM"),
    ]
    surface = [
        SurfacePoint(90, 0.30),
        SurfacePoint(95, 0.26),
        SurfacePoint(100, 0.24),
        SurfacePoint(105, 0.25),
        SurfacePoint(110, 0.29),
    ]

    result = build_forecast_surface_intelligence(
        forecasts,
        surface,
        bootstrap_samples=20,
    )

    assert result.readiness_state == "ACCUMULATING_FORECAST_COMPARISON"
    assert result.decision_authority == "NONE_RESEARCH_ONLY"
