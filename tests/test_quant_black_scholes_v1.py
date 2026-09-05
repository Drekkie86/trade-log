from __future__ import annotations

import math

import pytest

from src.quant.black_scholes import black76_price, no_arbitrage_bounds, price
from src.quant.types import QuantInputError, VanillaOption


def test_bsm_known_call_value():
    option = VanillaOption(100, 100, 1, 0.05, 0.2, "CALL", 0.0)
    assert price(option) == pytest.approx(10.450583572, rel=1e-9)


def test_bsm_known_put_value():
    option = VanillaOption(100, 100, 1, 0.05, 0.2, "PUT", 0.0)
    assert price(option) == pytest.approx(5.573526022, rel=1e-9)


def test_put_call_parity_with_dividend():
    call = VanillaOption(120, 110, 0.75, 0.03, 0.28, "CALL", 0.015)
    put = VanillaOption(120, 110, 0.75, 0.03, 0.28, "PUT", 0.015)
    lhs = price(call) - price(put)
    rhs = 120 * math.exp(-0.015 * 0.75) - 110 * math.exp(-0.03 * 0.75)
    assert lhs == pytest.approx(rhs, abs=1e-11)


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_expiry_is_intrinsic(right):
    option = VanillaOption(105, 100, 0, 0.03, 0.2, right)
    expected = 5.0 if right == "CALL" else 0.0
    assert price(option) == expected


def test_zero_volatility_is_discounted_deterministic_payoff():
    option = VanillaOption(100, 100, 1, 0.05, 0.0, "CALL")
    expected = math.exp(-0.05) * (100 * math.exp(0.05) - 100)
    assert price(option) == pytest.approx(expected)


def test_no_arbitrage_bounds_contain_price():
    option = VanillaOption(90, 100, 0.4, 0.02, 0.35, "PUT", 0.01)
    lower, upper = no_arbitrage_bounds(option)
    value = price(option)
    assert lower <= value <= upper


def test_black76_known_atm_is_positive():
    value = black76_price(100, 100, 1, 0.05, 0.2, "CALL")
    assert value == pytest.approx(7.577082146, rel=1e-9)


def test_black76_put_call_parity():
    call = black76_price(105, 100, 0.5, 0.02, 0.3, "CALL")
    put = black76_price(105, 100, 0.5, 0.02, 0.3, "PUT")
    assert call - put == pytest.approx(math.exp(-0.02 * 0.5) * 5.0)


@pytest.mark.parametrize(
    "option",
    [
        VanillaOption(0, 100, 1, 0.0, 0.2, "CALL"),
        VanillaOption(100, 0, 1, 0.0, 0.2, "CALL"),
        VanillaOption(100, 100, -1, 0.0, 0.2, "CALL"),
        VanillaOption(100, 100, 1, 0.0, -0.2, "CALL"),
        VanillaOption(100, 100, 1, 0.0, 0.2, "BAD"),
    ],
)
def test_invalid_vanilla_domain_fails(option):
    with pytest.raises(QuantInputError):
        price(option)
