from __future__ import annotations

import numpy as np
import pytest

import src.quant.rolling_variance_forecast as rolling
import src.research.edge_risk_runtime_v1 as edge_runtime
from src.quant.types import QuantInputError
from src.quant.vol_forecast import GARCH11Fit, require_usable_garch_fit


def _failed_fit() -> GARCH11Fit:
    return GARCH11Fit(
        omega=1e-6,
        alpha=0.05,
        beta=0.90,
        unconditional_variance=2e-5,
        last_variance=1e-4,
        next_variance=1e-4,
        converged=False,
        log_likelihood=-123.0,
        message="forced optimizer failure",
    )


def test_failed_garch_fit_is_not_usable_research_evidence() -> None:
    with pytest.raises(QuantInputError, match="did not converge"):
        require_usable_garch_fit(_failed_fit())


def test_rolling_forecast_refuses_nonconverged_garch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rolling, "fit_garch11", lambda returns: _failed_fit())
    returns = np.random.default_rng(11).normal(0.0, 0.01, size=50)

    with pytest.raises(QuantInputError, match="did not converge"):
        rolling.rolling_variance_forecasts(
            returns,
            config=rolling.RollingForecastConfig(
                train_window=30,
                horizon_days=5,
                include_garch=True,
            ),
        )


def test_current_garch_forecast_refuses_nonconverged_fit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(edge_runtime, "fit_garch11", lambda returns: _failed_fit())
    returns = np.random.default_rng(17).normal(0.0, 0.01, size=50)

    with pytest.raises(QuantInputError, match="did not converge"):
        edge_runtime._current_forecast(
            returns,
            model_id=rolling.GARCH11_MODEL_ID,
            train_window=40,
            horizon_days=5,
            ewma_decay=0.94,
        )
