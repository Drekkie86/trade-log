from __future__ import annotations

import numpy as np
import pytest

from src.quant.rolling_variance_forecast import (
    EWMA_MODEL_ID,
    GARCH11_MODEL_ID,
    HISTORICAL_VARIANCE_MODEL_ID,
)
from src.research.edge_risk_runtime_v1 import _current_forecast, _forecast_error_std
from src.quant.forecast_validation import ForecastObservation


def test_current_forecast_supports_all_package_b_models() -> None:
    returns = np.asarray([0.001 * ((index % 9) - 4) for index in range(80)], dtype=float)
    historical = _current_forecast(
        returns,
        model_id=HISTORICAL_VARIANCE_MODEL_ID,
        train_window=40,
        horizon_days=5,
        ewma_decay=0.94,
    )
    ewma = _current_forecast(
        returns,
        model_id=EWMA_MODEL_ID,
        train_window=40,
        horizon_days=5,
        ewma_decay=0.94,
    )
    garch = _current_forecast(
        returns,
        model_id=GARCH11_MODEL_ID,
        train_window=40,
        horizon_days=5,
        ewma_decay=0.94,
    )
    assert historical > 0
    assert ewma > 0
    assert garch > 0


def test_forecast_error_std_uses_only_selected_model() -> None:
    rows = (
        ForecastObservation("A", 0.10, 0.08, 5),
        ForecastObservation("A", 0.12, 0.09, 5),
        ForecastObservation("B", 10.0, 1.0, 5),
    )
    result = _forecast_error_std(rows, model_id="A")
    assert result == pytest.approx(np.std([0.02, 0.03], ddof=1))
    assert _forecast_error_std(rows, model_id="B") is None


def test_unknown_current_forecast_model_fails_explicitly() -> None:
    returns = np.asarray([0.001 * ((index % 7) - 3) for index in range(50)], dtype=float)
    with pytest.raises(ValueError, match="unsupported forecast model"):
        _current_forecast(
            returns,
            model_id="UNKNOWN",
            train_window=40,
            horizon_days=5,
            ewma_decay=0.94,
        )
