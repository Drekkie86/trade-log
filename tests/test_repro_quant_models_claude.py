"""Reproductions from the 2026-10-17 numerical verification of src/quant.

Each test states the *desired* behaviour and is a strict xfail: it fails today
and will flip to XPASS (and break the build) once the defect is fixed, which is
the signal to delete the marker.
"""
import cmath
import math

import pytest
from scipy.integrate import quad

from src.quant import black_scholes as bs
from src.quant import finite_difference as fd
from src.quant import greeks, heston
from src.quant.types import VanillaOption as O


def _lewis_call(S, K, T, r, q, p, upper=2000.0):
    """Independent Heston call price (Lewis 2001), integrated far into the tail."""
    fwd = S * math.exp((r - q) * T)
    k = math.log(fwd / K)

    def phi(u):
        z = heston.characteristic_function(
            u, spot=S, time_to_expiry=T, rate=r, dividend_yield=q, params=p
        )
        return z * cmath.exp(-1j * u * (math.log(S) + (r - q) * T))

    def f(u):
        return (cmath.exp(1j * u * k) * phi(u - 0.5j)).real / (u * u + 0.25)

    integral, _ = quad(f, 0, upper, limit=2000, epsabs=1e-12, epsrel=1e-12)
    return math.exp(-r * T) * (fwd - math.sqrt(K * fwd) / math.pi * integral)


@pytest.mark.xfail(strict=True, reason="REVIEW 20261017: Heston integrates only to u=120 (80 in calibrate); "
                   "prices are silently wrong by up to ~5% (14% at 80) at realistic Feller-violating parameters")
def test_heston_price_matches_independent_integration_at_realistic_parameters():
    p = heston.HestonParameters(kappa=1.0, theta=0.04, vol_of_vol=1.0, rho=-0.8, v0=0.04)
    o = O(100, 110, 0.25, 0.03, 0.2, "CALL", 0.01)   # true price 0.156126; module 0.148666
    assert abs(heston.price(o, p) - _lewis_call(100, 110, 0.25, 0.03, 0.01, p)) < 1e-4


@pytest.mark.xfail(strict=True, reason="REVIEW 20261017: Heston short-dated ATM price off ~1.6% with no warning")
def test_heston_short_dated_atm_price_is_accurate():
    p = heston.HestonParameters(kappa=2.0, theta=0.04, vol_of_vol=0.3, rho=-0.7, v0=0.04)
    o = O(100, 100, 0.01, 0.03, 0.2, "CALL", 0.01)    # true 0.807101; module 0.794078
    assert abs(heston.price(o, p) - _lewis_call(100, 100, 0.01, 0.03, 0.01, p)) < 1e-4


@pytest.mark.xfail(strict=True, reason="REVIEW 20261017: Crank-Nicolson is 1.7% low for ATM T=0.003y yet reports "
                   "CONVERGED_DOMAIN_AND_RESOLUTION (non-smooth payoff at the grid kink)")
def test_crank_nicolson_atm_one_day_matches_black_scholes():
    o = O(100, 100, 0.003, 0.04, 0.25, "CALL")
    d = fd.crank_nicolson_diagnostic(o)
    assert d.converged
    assert abs(d.price - bs.price(o)) / bs.price(o) < 0.002


@pytest.mark.xfail(strict=True, reason="REVIEW 20261017: charm has the wrong sign on the dividend term "
                   "(identical to -dDelta/dT only when q == 0). Not used downstream.")
def test_charm_with_dividend_matches_numerical_derivative():
    def delta(T):
        return greeks.analytic(O(100, 105, T, 0.04, 0.3, "CALL", 0.03)).delta
    h = 1e-6
    numeric = -(delta(0.5 + h) - delta(0.5 - h)) / (2 * h)
    assert abs(greeks.analytic(O(100, 105, 0.5, 0.04, 0.3, "CALL", 0.03)).charm - numeric) < 1e-5
