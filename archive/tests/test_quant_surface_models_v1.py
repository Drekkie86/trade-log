from __future__ import annotations

import numpy as np
import pytest

from src.quant.black_scholes import price
from src.quant.local_vol import dupire_from_call_grid
from src.quant.sabr import SABRParameters, hagan_lognormal_iv
from src.quant.surface import SmileSlice, diagnose_calendar_total_variance, diagnose_call_slice
from src.quant.svi import SVIParameters, calibrate, minimum_total_variance, sampled_static_arbitrage, total_variance
from src.quant.types import QuantInputError, VanillaOption


def test_smile_slice_interpolates_total_variance_and_hits_knots():
    k = [-0.2, 0.0, 0.2]
    iv = [0.30, 0.25, 0.28]
    smile = SmileSlice(k, iv, 0.5)
    assert smile.iv(0.0) == pytest.approx(0.25)
    mid = smile.iv(0.1)
    assert 0.24 < mid < 0.30


def test_smile_slice_refuses_extrapolation():
    smile = SmileSlice([-0.1, 0.0, 0.1], [0.25, 0.2, 0.24], 0.5)
    with pytest.raises(QuantInputError):
        smile.iv(0.5)


def test_call_slice_static_arbitrage_clean_for_bsm_prices():
    strikes = [80, 90, 100, 110, 120]
    calls = [price(VanillaOption(100, k, 0.5, 0.02, 0.25, "CALL")) for k in strikes]
    result = diagnose_call_slice(100, strikes, calls, time_to_expiry=0.5, rate=0.02)
    assert result == {
        "call_monotonicity_violations": 0,
        "call_convexity_violations": 0,
        "call_bound_violations": 0,
    }


def test_call_slice_detects_monotonicity_violation():
    result = diagnose_call_slice(
        100,
        [90, 100, 110],
        [12, 14, 3],
        time_to_expiry=0.5,
        rate=0.0,
    )
    assert result["call_monotonicity_violations"] >= 1


def test_calendar_total_variance_detects_decrease():
    assert diagnose_calendar_total_variance([0.25, 0.5], [0.40, 0.20]) == 1


def test_svi_total_variance_positive_for_reasonable_params():
    params = SVIParameters(0.01, 0.1, -0.4, 0.0, 0.2)
    values = total_variance(np.linspace(-1, 1, 21), params)
    assert np.all(values > 0)
    assert minimum_total_variance(params) > 0


def test_svi_calibration_recovers_synthetic_smile():
    true = SVIParameters(0.02, 0.15, -0.35, 0.02, 0.18)
    k = np.linspace(-0.4, 0.4, 11)
    t = 0.5
    iv = np.sqrt(total_variance(k, true) / t)
    result = calibrate(k, iv, t, initial=true)
    assert result.diagnostics.converged
    assert result.diagnostics.rmse < 1e-9


def test_svi_sampled_diagnostics_report_nonnegative_variance():
    result = sampled_static_arbitrage(SVIParameters(0.02, 0.1, -0.3, 0.0, 0.2))
    assert result["negative_total_variance"] is False


def test_sabr_atm_iv_is_positive():
    params = SABRParameters(alpha=0.25, beta=0.7, rho=-0.3, nu=0.5)
    iv = hagan_lognormal_iv(100, 100, 1, params)
    assert 0 < iv < 2


def test_sabr_continuity_near_atm():
    params = SABRParameters(alpha=0.25, beta=0.7, rho=-0.3, nu=0.5)
    atm = hagan_lognormal_iv(100, 100, 1, params)
    near = hagan_lognormal_iv(100, 100.0001, 1, params)
    assert near == pytest.approx(atm, rel=1e-4)


def test_dupire_recovers_reasonable_local_vol_from_bsm_grid():
    strikes = np.linspace(80, 120, 9)
    expiries = np.linspace(0.15, 1.0, 7)
    sigma = 0.25
    grid = [
        [price(VanillaOption(100, float(k), float(t), 0.02, sigma, "CALL")) for k in strikes]
        for t in expiries
    ]
    points = dupire_from_call_grid(strikes, expiries, grid, rate=0.02)
    valid = [p.local_volatility for p in points if p.state == "VALID"]
    assert valid
    assert float(np.median(valid)) == pytest.approx(sigma, abs=0.04)
