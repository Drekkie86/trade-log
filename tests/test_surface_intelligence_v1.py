import pytest

from src.research.surface_intelligence_v1 import (
    CHALLENGER_MODEL_ID,
    INCUMBENT_MODEL_ID,
    SurfacePoint,
    compare_surface_models,
)


def test_surface_tournament_compares_only_interior_points() -> None:
    points = [
        SurfacePoint(90, 0.30),
        SurfacePoint(95, 0.26),
        SurfacePoint(100, 0.24),
        SurfacePoint(105, 0.25),
        SurfacePoint(110, 0.29),
        SurfacePoint(115, 0.35),
    ]

    result = compare_surface_models(points)

    assert result.incumbent_model_id == INCUMBENT_MODEL_ID
    assert result.challenger_model_id == CHALLENGER_MODEL_ID
    assert result.point_count == 6
    assert result.evaluable_count == 4
    assert result.promotion_state == "RESEARCH_ONLY_CHALLENGER"
    assert result.incumbent_mae is not None
    assert result.challenger_mae is not None
    assert result.challenger_win_rate is not None
    assert 0 <= result.challenger_win_rate <= 1
    assert result.sign_agreement_rate is not None
    assert 0 <= result.sign_agreement_rate <= 1


def test_quadratic_incumbent_is_exact_on_quadratic_smile() -> None:
    points = [
        SurfacePoint(strike, 0.20 + 0.0001 * (strike - 100.0) ** 2)
        for strike in (85, 90, 95, 100, 105, 110, 115)
    ]

    result = compare_surface_models(points)

    assert result.incumbent_mae == pytest.approx(0.0, abs=1e-12)
    assert result.incumbent_rmse == pytest.approx(0.0, abs=1e-12)
    assert result.challenger_mae is not None and result.challenger_mae > 0


def test_duplicate_strikes_are_rejected() -> None:
    points = [
        SurfacePoint(90, 0.3),
        SurfacePoint(95, 0.28),
        SurfacePoint(100, 0.25),
        SurfacePoint(100, 0.24),
        SurfacePoint(105, 0.26),
    ]
    with pytest.raises(Exception, match="unique"):
        compare_surface_models(points)
