"""Heston integration must include the Fourier tail, even at a finite split.

The old price(limit=80/120) cut off a material and oscillatory tail while
reported quad success only covered the truncated region. This data set uses
a converged high-cutoff external reference against the same characteristic
function to prevent a regression, NOT real market calibration evidence.
"""
import math

import pytest

from src.quant.heston import HestonParameters, calibrate, price
from src.quant.types import VanillaOption


SEVERE = HestonParameters(1.0, .04, 1.0, -.8, .04)
OPTION = VanillaOption(100, 110, .25, .04, .20, "CALL")


@pytest.mark.parametrize("limit", [80.0, 120.0, 240.0, float("inf")])
def test_heston_price_includes_fourier_tail_at_any_split(limit):
    value = price(OPTION, SEVERE, integration_limit=limit)
    # Stable 480->infinity price with this characteristic function:
    # 480 0.18622191445576686, infinity 0.186221873622463.
    assert value == pytest.approx(0.186221873622463, abs=0.0001)


@pytest.mark.parametrize("strike, maturity", [(90.0, .25), (100.0, .05), (110.0, .01)])
def test_short_duration_heston_split_matches_infinite_reference(strike, maturity):
    option = VanillaOption(100, strike, maturity, .04, .20, "CALL", .015)
    reference = price(option, SEVERE, integration_limit=float("inf"))
    for cutoff in (80.0, 120.0):
        assert price(option, SEVERE, integration_limit=cutoff) == pytest.approx(
            reference, abs=0.0002
        )


def test_heston_calibration_uses_tail_consistent_pricing():
    params = HestonParameters(1.2, .04, .7, -.6, .05)
    contracts = [
        VanillaOption(100, strike, maturity, .025, .2, "CALL", .01)
        for strike, maturity in ((90,.15), (100,.15), (110,.25), (95,.4), (105,.5))
    ]
    observations = [price(o, params, integration_limit=float("inf")) for o in contracts]
    fitted = calibrate(
        contracts, observations, initial=params,
        max_nfev=2, integration_limit=80.0,
    )
    assert fitted.diagnostics.rmse < 1e-5
    assert all(math.isfinite(p) for p in observations)



@pytest.mark.parametrize("bad_limit", [-1.0, 0.0, float("nan"), -float("inf")])
def test_heston_rejects_invalid_integration_boundary(bad_limit):
    from src.quant.types import QuantInputError

    with pytest.raises(QuantInputError):
        price(OPTION, SEVERE, integration_limit=bad_limit)
