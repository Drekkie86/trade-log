import numpy as np

from src.quant.forecast_validation import tournament
from src.quant.rolling_variance_forecast import (
    EWMA_MODEL_ID,
    GARCH11_MODEL_ID,
    HISTORICAL_VARIANCE_MODEL_ID,
    RollingForecastConfig,
    rolling_variance_forecasts,
)


def test_rolling_forecast_builds_three_comparable_models() -> None:
    rng = np.random.default_rng(7)
    returns = rng.normal(0.0, 0.01, size=80)

    rows = rolling_variance_forecasts(
        returns,
        config=RollingForecastConfig(train_window=40, horizon_days=5, include_garch=True),
    )

    model_ids = {item.model_id for item in rows}
    assert model_ids == {
        HISTORICAL_VARIANCE_MODEL_ID,
        EWMA_MODEL_ID,
        GARCH11_MODEL_ID,
    }
    assert len(rows) == (80 - 40 - 5 + 1) * 3
    assert all(item.forecast_variance > 0 for item in rows)
    assert all(item.realized_variance > 0 for item in rows)
    assert all(item.origin_index is not None for item in rows)

    result = tournament(rows, bootstrap_samples=50)
    assert result.comparable_model_count == 3
    assert set(result.ranking) == model_ids
    if result.winner is None:
        assert result.selection_state in {
            "NO_SIGNIFICANT_WINNER",
            "INSUFFICIENT_COMPARISON_EVIDENCE",
        }
    else:
        assert result.winner in model_ids
        assert result.selection_state == "EVIDENCE_SUPPORTED_WINNER"
        assert all(item.supports_candidate for item in result.comparisons)


def test_regime_labels_use_only_trailing_training_window() -> None:
    calm = np.full(40, 0.005)
    turbulent_tail = np.concatenate([np.full(25, 0.005), np.full(15, 0.03)])
    future = np.full(5, 0.01)
    returns = np.concatenate([calm, turbulent_tail, future])

    rows = rolling_variance_forecasts(
        returns,
        config=RollingForecastConfig(train_window=40, horizon_days=5, include_garch=False),
    )

    assert {item.model_id for item in rows} == {
        HISTORICAL_VARIANCE_MODEL_ID,
        EWMA_MODEL_ID,
    }
    assert all(item.regime in {"CALM", "NORMAL", "STRESS"} for item in rows)
