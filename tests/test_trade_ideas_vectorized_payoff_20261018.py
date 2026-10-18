"""Guard the vectorized payoff grid against the pre-optimization scalar math."""
import math

import numpy as np
import pytest
from scipy.stats import norm

from src.decision.trade_ideas import (
    IdeaLeg, MarketInputs, entry_cashflow_usd, profit_profile, terminal_value_usd,
)


def scalar_reference(legs, market, *, atm_iv, fees_usd, grid_points):
    cash = entry_cashflow_usd(legs)
    def payoff(s):
        return cash + terminal_value_usd(legs, s) - fees_usd
    strikes = [leg.strike for leg in legs]
    sigma_t = atm_iv * math.sqrt(market.t_years)
    drift = (market.rate - market.dividend_yield - 0.5 * atm_iv**2) * market.t_years
    lo = min(min(strikes), market.spot) * math.exp(-6.0 * sigma_t)
    hi = max(max(strikes), market.spot) * math.exp(6.0 * sigma_t)
    grid = np.exp(np.linspace(math.log(lo), math.log(hi), grid_points))
    pay = np.array([payoff(float(s)) for s in grid])
    probs = np.array([
        float(norm.cdf((math.log(float(s) / market.spot) - drift) / sigma_t))
        for s in grid
    ])
    p = 0.0
    if pay[0] > 0.0:
        p += probs[0]
    if pay[-1] > 0.0:
        p += 1.0 - probs[-1]
    p += float(np.diff(probs)[((pay[:-1] + pay[1:]) / 2.0) > 0.0].sum())
    breakevens = []
    for i in range(len(grid) - 1):
        a, b = pay[i], pay[i + 1]
        if a <= 0.0 < b or b <= 0.0 < a:
            frac = a / (a - b)
            breakevens.append(float(grid[i] + frac * (grid[i + 1] - grid[i])))
    return p, tuple(breakevens), min(pay), max(pay)


@pytest.mark.parametrize("right", ["C", "P"])
@pytest.mark.parametrize("long", [True, False])
@pytest.mark.parametrize("spot,vol,years", [
    (99.0, 0.18, 7/365), (103.0, 0.45, 30/365), (145.0, 0.70, 3/365),
])
@pytest.mark.parametrize("points", [101, 6001])
def test_vectorized_grid_preserves_scalar_reference(right, long, spot, vol, years, points):
    orientation = (("BUY", 1), ("SELL", 2), ("BUY", 1))
    if not long:
        orientation = (("SELL", 1), ("BUY", 2), ("SELL", 1))
    legs = tuple(
        IdeaLeg(option_quote_id=i, right=right, strike=strike, side=side,
                quantity=qty, multiplier=100.0, entry_price=px,
                bid=px - .05, ask=px + .05, market_iv=vol)
        for i, (strike, px, (side,qty)) in enumerate(
            zip((95., 100., 105.), (9., 7., 5.), orientation), start=1
        )
    )
    market = MarketInputs(spot=spot, t_years=years, rate=.04,
                          dividend_yield=.01, rate_and_yield_stored=True)
    actual = profit_profile(legs, market, atm_iv=vol, fees_usd=24.0, grid_points=points)
    expected_p, expected_bes, _, _ = scalar_reference(
        legs, market, atm_iv=vol, fees_usd=24.0, grid_points=points,
    )
    assert actual.p_profit == pytest.approx(expected_p, abs=1e-12)
    assert actual.breakevens == pytest.approx(expected_bes, abs=1e-9)
