from __future__ import annotations

import pytest

from src.quant.black_scholes import price as bsm_price
from src.quant.heston import HestonParameters, calibrate as calibrate_heston, price as heston_price
from src.quant.merton_jump import MertonJumpParameters, price as merton_price
from src.quant.types import QuantInputError, VanillaOption


def test_heston_zero_vol_of_vol_limit_matches_bsm():
    option = VanillaOption(100, 100, 1, 0.03, 0.2, "CALL", 0.01)
    params = HestonParameters(1.5, 0.04, 1e-12, -0.5, 0.04)
    assert heston_price(option, params) == pytest.approx(bsm_price(option), abs=1e-12)


def test_heston_call_and_put_obey_parity():
    call = VanillaOption(100, 105, 0.75, 0.02, 0.2, "CALL", 0.01)
    put = VanillaOption(100, 105, 0.75, 0.02, 0.2, "PUT", 0.01)
    params = HestonParameters(1.2, 0.05, 0.5, -0.6, 0.04)
    c = heston_price(call, params)
    p = heston_price(put, params)
    import math
    target = 100 * math.exp(-0.01 * 0.75) - 105 * math.exp(-0.02 * 0.75)
    assert c - p == pytest.approx(target, abs=1e-8)


def test_heston_feller_ratio_exposed():
    params = HestonParameters(2.0, 0.04, 0.4, -0.5, 0.04)
    assert params.feller_ratio == pytest.approx(1.0)


def test_heston_invalid_rho_rejected():
    with pytest.raises(QuantInputError):
        HestonParameters(1, 0.04, 0.4, 1.0, 0.04).validate()


def test_heston_calibration_returns_diagnostics_on_synthetic_prices():
    true = HestonParameters(1.4, 0.04, 0.35, -0.55, 0.045)
    options = [
        VanillaOption(100, strike, expiry, 0.02, 0.2, "CALL", 0.01)
        for expiry, strike in [(0.25, 90), (0.25, 100), (0.25, 110), (0.5, 95), (0.5, 105)]
    ]
    prices = [heston_price(o, true, integration_limit=60) for o in options]
    result = calibrate_heston(
        options,
        prices,
        initial=true,
        max_nfev=3,
        integration_limit=60,
    )
    assert result.diagnostics.rmse < 1e-7
    assert result.diagnostics.observations == 5


def test_merton_zero_jump_limit_matches_bsm():
    option = VanillaOption(100, 100, 1, 0.03, 0.2, "CALL", 0.01)
    params = MertonJumpParameters(0.0, 0.0, 0.0)
    assert merton_price(option, params) == pytest.approx(bsm_price(option), abs=1e-10)


def test_merton_jump_price_is_positive_and_finite():
    option = VanillaOption(100, 120, 0.5, 0.02, 0.25, "PUT")
    params = MertonJumpParameters(0.6, -0.08, 0.25)
    value = merton_price(option, params)
    assert 0 < value < 120


def test_merton_invalid_jump_intensity_rejected():
    with pytest.raises(QuantInputError):
        merton_price(
            VanillaOption(100, 100, 1, 0.02, 0.2, "CALL"),
            MertonJumpParameters(-1, 0, 0.2),
        )
