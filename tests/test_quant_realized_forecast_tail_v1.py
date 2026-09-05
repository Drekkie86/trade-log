from __future__ import annotations

import numpy as np
import pytest

from src.quant.event_risk import implied_event_variance
from src.quant.realized_vol import close_to_close, garman_klass, parkinson, rogers_satchell, yang_zhang
from src.quant.tails import diagnose
from src.quant.vol_forecast import ewma_variance, fit_garch11


def _synthetic_ohlc(n=80):
    rng = np.random.default_rng(7)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    open_ = np.concatenate([[100.0], close[:-1] * np.exp(rng.normal(0, 0.003, n - 1))])
    high = np.maximum(open_, close) * np.exp(np.abs(rng.normal(0, 0.006, n)))
    low = np.minimum(open_, close) * np.exp(-np.abs(rng.normal(0, 0.006, n)))
    return open_, high, low, close


def test_realized_vol_estimators_are_positive():
    o, h, l, c = _synthetic_ohlc()
    values = [
        close_to_close(c),
        parkinson(h, l),
        garman_klass(o, h, l, c),
        rogers_satchell(o, h, l, c),
        yang_zhang(o, h, l, c),
    ]
    assert all(0 < value < 2 for value in values)


def test_ewma_variance_is_positive_and_deterministic():
    returns = np.linspace(-0.02, 0.02, 100)
    a = ewma_variance(returns)
    b = ewma_variance(returns)
    assert a == b
    assert a > 0


def test_garch_fit_stationary_and_finite():
    rng = np.random.default_rng(123)
    returns = rng.normal(0, 0.01, 300)
    fit = fit_garch11(returns)
    assert fit.omega > 0
    assert 0 <= fit.alpha < 1
    assert 0 <= fit.beta < 1
    assert fit.alpha + fit.beta < 0.9991
    assert fit.next_variance > 0


def test_tail_diagnostics_order_cvar_above_var():
    rng = np.random.default_rng(42)
    returns = rng.standard_t(df=5, size=2000) * 0.01
    result = diagnose(returns)
    assert result.cvar_95 >= result.var_95
    assert result.cvar_99 >= result.var_99
    assert result.var_99 >= result.var_95


def test_event_variance_decomposition_never_negative():
    result = implied_event_variance(0.20, 0.1, baseline_variance_rate=0.25**2)
    assert result["event_variance"] == 0.0


def test_event_variance_detects_excess_total_variance():
    result = implied_event_variance(0.50, 0.1, baseline_variance_rate=0.20**2)
    assert result["event_variance"] > 0
