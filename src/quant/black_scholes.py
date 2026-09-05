from __future__ import annotations

import math

from scipy.stats import norm

from src.quant.types import QuantInputError, VanillaOption


def _discount(rate: float, time: float) -> float:
    return math.exp(-rate * time)


def no_arbitrage_bounds(option: VanillaOption) -> tuple[float, float]:
    option.validate()
    right = option.normalized_right()
    t = option.time_to_expiry
    s_disc = option.spot * _discount(option.dividend_yield, t)
    k_disc = option.strike * _discount(option.rate, t)
    if right == "CALL":
        return max(0.0, s_disc - k_disc), s_disc
    return max(0.0, k_disc - s_disc), k_disc


def _deterministic_price(option: VanillaOption) -> float:
    t = option.time_to_expiry
    terminal_forward = option.spot * math.exp(
        (option.rate - option.dividend_yield) * t
    )
    if option.normalized_right() == "CALL":
        payoff = max(terminal_forward - option.strike, 0.0)
    else:
        payoff = max(option.strike - terminal_forward, 0.0)
    return _discount(option.rate, t) * payoff


def d1_d2(option: VanillaOption) -> tuple[float, float]:
    option.validate()
    t = option.time_to_expiry
    sigma = option.volatility
    if t <= 0.0 or sigma <= 0.0:
        raise QuantInputError("d1/d2 require positive time and volatility")
    root_t = math.sqrt(t)
    d1 = (
        math.log(option.spot / option.strike)
        + (
            option.rate
            - option.dividend_yield
            + 0.5 * sigma * sigma
        )
        * t
    ) / (sigma * root_t)
    return d1, d1 - sigma * root_t


def price(option: VanillaOption) -> float:
    option.validate()
    t = option.time_to_expiry
    if t == 0.0:
        if option.normalized_right() == "CALL":
            return max(option.spot - option.strike, 0.0)
        return max(option.strike - option.spot, 0.0)
    if option.volatility == 0.0:
        return _deterministic_price(option)

    d1, d2 = d1_d2(option)
    s_disc = option.spot * _discount(option.dividend_yield, t)
    k_disc = option.strike * _discount(option.rate, t)
    if option.normalized_right() == "CALL":
        return s_disc * norm.cdf(d1) - k_disc * norm.cdf(d2)
    return k_disc * norm.cdf(-d2) - s_disc * norm.cdf(-d1)


def call_price(
    spot: float,
    strike: float,
    time_to_expiry: float,
    rate: float,
    volatility: float,
    dividend_yield: float = 0.0,
) -> float:
    return price(
        VanillaOption(
            spot=spot,
            strike=strike,
            time_to_expiry=time_to_expiry,
            rate=rate,
            volatility=volatility,
            right="CALL",
            dividend_yield=dividend_yield,
        )
    )


def put_price(
    spot: float,
    strike: float,
    time_to_expiry: float,
    rate: float,
    volatility: float,
    dividend_yield: float = 0.0,
) -> float:
    return price(
        VanillaOption(
            spot=spot,
            strike=strike,
            time_to_expiry=time_to_expiry,
            rate=rate,
            volatility=volatility,
            right="PUT",
            dividend_yield=dividend_yield,
        )
    )


def black76_price(
    forward: float,
    strike: float,
    time_to_expiry: float,
    rate: float,
    volatility: float,
    right: str = "CALL",
) -> float:
    right = right.upper()
    if right not in {"CALL", "PUT"}:
        raise QuantInputError("right must be CALL or PUT")
    if forward <= 0 or strike <= 0:
        raise QuantInputError("forward and strike must be positive")
    if time_to_expiry < 0 or volatility < 0:
        raise QuantInputError("time and volatility cannot be negative")
    if time_to_expiry == 0:
        intrinsic = max(forward - strike, 0.0)
        if right == "PUT":
            intrinsic = max(strike - forward, 0.0)
        return intrinsic
    if volatility == 0:
        intrinsic = max(forward - strike, 0.0)
        if right == "PUT":
            intrinsic = max(strike - forward, 0.0)
        return _discount(rate, time_to_expiry) * intrinsic

    root_t = math.sqrt(time_to_expiry)
    d1 = (
        math.log(forward / strike)
        + 0.5 * volatility * volatility * time_to_expiry
    ) / (volatility * root_t)
    d2 = d1 - volatility * root_t
    disc = _discount(rate, time_to_expiry)
    if right == "CALL":
        return disc * (
            forward * norm.cdf(d1) - strike * norm.cdf(d2)
        )
    return disc * (
        strike * norm.cdf(-d2) - forward * norm.cdf(-d1)
    )
