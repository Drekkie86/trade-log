"""Short-dated Crank-Nicolson must not claim inaccurate convergence.

This cross-model numerical check compares a European-option BSM PDE to the
independent analytic BSM formula under the *same* inputs. A 1.7% pricing
error at ~1 day formerly reported CONVERGED_DOMAIN_AND_RESOLUTION.
"""
import pytest

from src.quant.black_scholes import price as black_scholes
from src.quant.finite_difference import crank_nicolson_diagnostic
from src.quant.types import VanillaOption


@pytest.mark.parametrize("right", ["CALL", "PUT"])
@pytest.mark.parametrize("maturity", [0.003, 0.001])
def test_short_maturity_pde_cannot_report_bad_convergence(right, maturity):
    option = VanillaOption(
        spot=100.0, strike=100.0, time_to_expiry=maturity,
        rate=0.04, volatility=0.25, right=right, dividend_yield=0.0,
    )
    diagnostic = crank_nicolson_diagnostic(option)
    benchmark = black_scholes(option)
    assert diagnostic.converged is True
    assert diagnostic.state == "CONVERGED_DOMAIN_AND_RESOLUTION"
    assert diagnostic.final_spot_steps >= 3200
    # Half a cent / share AND half a percent, at this exact synthetic input.
    # This is not a claim of broker execution accuracy.
    assert abs(diagnostic.price - benchmark) <= min(0.005, 0.005 * abs(benchmark))


def test_noncontracting_resolution_fails_closed(monkeypatch):
    from src.quant import finite_difference as cn

    def unresolved(option, *, spot_steps, time_steps, spot_max_multiple):
        # Domain widening gives the SAME price, but every 2x grid change
        # moves the result by 1.0. This cannot be called convergence.
        return float(spot_steps // 800)

    monkeypatch.setattr(cn, "_crank_nicolson_on_grid", unresolved)
    option = VanillaOption(100, 100, 0.003, 0.04, 0.25, "CALL")
    report = cn.crank_nicolson_diagnostic(option)
    assert report.converged is False
    assert report.state == "RESOLUTION_CONVERGENCE_NOT_DEMONSTRATED"
