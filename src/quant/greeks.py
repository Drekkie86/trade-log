from __future__ import annotations

import math

from scipy.stats import norm

from src.quant.black_scholes import d1_d2, price
from src.quant.types import Greeks, QuantInputError, VanillaOption


def analytic(option: VanillaOption) -> Greeks:
    option.validate()
    t = option.time_to_expiry
    sigma = option.volatility
    if t <= 0.0 or sigma <= 0.0:
        raise QuantInputError("analytic greeks require positive time and volatility")

    right = option.normalized_right()
    d1, d2 = d1_d2(option)
    root_t = math.sqrt(t)
    disc_q = math.exp(-option.dividend_yield * t)
    disc_r = math.exp(-option.rate * t)
    pdf = norm.pdf(d1)

    if right == "CALL":
        delta = disc_q * norm.cdf(d1)
        theta = (
            -option.spot * disc_q * pdf * sigma / (2.0 * root_t)
            - option.rate * option.strike * disc_r * norm.cdf(d2)
            + option.dividend_yield * option.spot * disc_q * norm.cdf(d1)
        )
        rho = option.strike * t * disc_r * norm.cdf(d2)
        charm = (
            -disc_q * (
                pdf
                * (
                    2.0 * (option.rate - option.dividend_yield) * t
                    - d2 * sigma * root_t
                )
                / (2.0 * t * sigma * root_t)
                + option.dividend_yield * norm.cdf(d1)
            )
        )
    else:
        delta = disc_q * (norm.cdf(d1) - 1.0)
        theta = (
            -option.spot * disc_q * pdf * sigma / (2.0 * root_t)
            + option.rate * option.strike * disc_r * norm.cdf(-d2)
            - option.dividend_yield * option.spot * disc_q * norm.cdf(-d1)
        )
        rho = -option.strike * t * disc_r * norm.cdf(-d2)
        charm = (
            -disc_q * (
                pdf
                * (
                    2.0 * (option.rate - option.dividend_yield) * t
                    - d2 * sigma * root_t
                )
                / (2.0 * t * sigma * root_t)
                - option.dividend_yield * norm.cdf(-d1)
            )
        )

    gamma = disc_q * pdf / (option.spot * sigma * root_t)
    vega = option.spot * disc_q * pdf * root_t
    vanna = -disc_q * pdf * d2 / sigma
    vomma = vega * d1 * d2 / sigma

    return Greeks(
        delta=float(delta),
        gamma=float(gamma),
        vega=float(vega),
        theta=float(theta),
        rho=float(rho),
        vanna=float(vanna),
        vomma=float(vomma),
        charm=float(charm),
    )


def numerical(
    option: VanillaOption,
    *,
    spot_step_fraction: float = 1e-4,
    vol_step: float = 1e-4,
    rate_step: float = 1e-5,
    time_step: float = 1e-5,
) -> dict[str, float]:
    option.validate()
    if option.time_to_expiry <= time_step or option.volatility <= vol_step:
        raise QuantInputError("numerical greeks require positive interior time/volatility")

    def with_values(**changes) -> VanillaOption:
        values = {
            "spot": option.spot,
            "strike": option.strike,
            "time_to_expiry": option.time_to_expiry,
            "rate": option.rate,
            "volatility": option.volatility,
            "right": option.right,
            "dividend_yield": option.dividend_yield,
        }
        values.update(changes)
        return VanillaOption(**values)

    h_s = max(option.spot * spot_step_fraction, 1e-6)
    p0 = price(option)
    p_up = price(with_values(spot=option.spot + h_s))
    p_dn = price(with_values(spot=option.spot - h_s))
    delta = (p_up - p_dn) / (2.0 * h_s)
    gamma = (p_up - 2.0 * p0 + p_dn) / (h_s * h_s)

    p_vu = price(with_values(volatility=option.volatility + vol_step))
    p_vd = price(with_values(volatility=option.volatility - vol_step))
    vega = (p_vu - p_vd) / (2.0 * vol_step)

    p_ru = price(with_values(rate=option.rate + rate_step))
    p_rd = price(with_values(rate=option.rate - rate_step))
    rho = (p_ru - p_rd) / (2.0 * rate_step)

    # theta convention: derivative with respect to calendar time passage,
    # so minus derivative with respect to time-to-expiry.
    p_tu = price(with_values(time_to_expiry=option.time_to_expiry + time_step))
    p_td = price(with_values(time_to_expiry=option.time_to_expiry - time_step))
    theta = -(p_tu - p_td) / (2.0 * time_step)

    return {
        "delta": float(delta),
        "gamma": float(gamma),
        "vega": float(vega),
        "theta": float(theta),
        "rho": float(rho),
    }
