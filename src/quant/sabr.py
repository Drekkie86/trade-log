from __future__ import annotations

from dataclasses import asdict, dataclass
import math

from src.quant.types import QuantInputError


@dataclass(frozen=True)
class SABRParameters:
    alpha: float
    beta: float
    rho: float
    nu: float

    def validate(self) -> None:
        if self.alpha <= 0:
            raise QuantInputError("SABR alpha must be positive")
        if not 0 <= self.beta <= 1:
            raise QuantInputError("SABR beta must be in [0,1]")
        if not -1 < self.rho < 1:
            raise QuantInputError("SABR rho must be strictly between -1 and 1")
        if self.nu < 0:
            raise QuantInputError("SABR nu cannot be negative")

    def as_dict(self) -> dict:
        return asdict(self)


def hagan_lognormal_iv(
    forward: float,
    strike: float,
    time_to_expiry: float,
    params: SABRParameters,
) -> float:
    params.validate()
    if forward <= 0 or strike <= 0:
        raise QuantInputError("forward and strike must be positive")
    if time_to_expiry < 0:
        raise QuantInputError("time_to_expiry cannot be negative")

    alpha, beta, rho, nu = params.alpha, params.beta, params.rho, params.nu
    one_minus_beta = 1.0 - beta
    fk = forward * strike

    if abs(forward - strike) <= 1e-12 * max(forward, strike):
        f_pow = forward ** one_minus_beta
        correction = (
            (one_minus_beta**2 / 24.0) * alpha**2 / (f_pow**2)
            + 0.25 * rho * beta * nu * alpha / f_pow
            + (2.0 - 3.0 * rho**2) * nu**2 / 24.0
        )
        return alpha / f_pow * (1.0 + correction * time_to_expiry)

    log_fk = math.log(forward / strike)
    fk_pow = fk ** (0.5 * one_minus_beta)
    denominator = fk_pow * (
        1.0
        + (one_minus_beta**2 / 24.0) * log_fk**2
        + (one_minus_beta**4 / 1920.0) * log_fk**4
    )
    z = (nu / alpha) * fk_pow * log_fk if nu > 0 else 0.0
    if abs(z) < 1e-10:
        z_over_x = 1.0
    else:
        x_z = math.log(
            (math.sqrt(1.0 - 2.0 * rho * z + z * z) + z - rho)
            / (1.0 - rho)
        )
        z_over_x = z / x_z

    correction = (
        (one_minus_beta**2 / 24.0) * alpha**2 / (fk_pow**2)
        + 0.25 * rho * beta * nu * alpha / fk_pow
        + (2.0 - 3.0 * rho**2) * nu**2 / 24.0
    )
    return alpha / denominator * z_over_x * (1.0 + correction * time_to_expiry)
