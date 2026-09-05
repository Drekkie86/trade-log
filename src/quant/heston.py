from __future__ import annotations

from dataclasses import asdict, dataclass
import cmath
import math
from typing import Sequence

import numpy as np
from scipy.integrate import quad
from scipy.optimize import least_squares

from src.quant.black_scholes import price as bsm_price
from src.quant.types import CalibrationDiagnostics, QuantInputError, VanillaOption


@dataclass(frozen=True)
class HestonParameters:
    kappa: float
    theta: float
    vol_of_vol: float
    rho: float
    v0: float

    def validate(self) -> None:
        if self.kappa <= 0:
            raise QuantInputError("kappa must be positive")
        if self.theta <= 0:
            raise QuantInputError("theta must be positive")
        if self.vol_of_vol < 0:
            raise QuantInputError("vol_of_vol cannot be negative")
        if not -1 < self.rho < 1:
            raise QuantInputError("rho must be strictly between -1 and 1")
        if self.v0 <= 0:
            raise QuantInputError("v0 must be positive")

    @property
    def feller_ratio(self) -> float:
        if self.vol_of_vol == 0:
            return math.inf
        return 2.0 * self.kappa * self.theta / (self.vol_of_vol**2)

    def as_dict(self) -> dict:
        return asdict(self)


def characteristic_function(
    u: complex,
    *,
    spot: float,
    time_to_expiry: float,
    rate: float,
    dividend_yield: float,
    params: HestonParameters,
) -> complex:
    params.validate()
    if spot <= 0 or time_to_expiry < 0:
        raise QuantInputError("invalid spot/time")
    if time_to_expiry == 0:
        return cmath.exp(1j * u * math.log(spot))
    if params.vol_of_vol <= 1e-10:
        sigma = math.sqrt(params.v0)
        mu = math.log(spot) + (
            rate - dividend_yield - 0.5 * sigma * sigma
        ) * time_to_expiry
        variance = sigma * sigma * time_to_expiry
        return cmath.exp(1j * u * mu - 0.5 * variance * u * u)

    kappa = params.kappa
    theta = params.theta
    eta = params.vol_of_vol
    rho = params.rho
    v0 = params.v0
    t = time_to_expiry

    iu = 1j * u
    b = kappa - rho * eta * iu
    d = cmath.sqrt(b * b + eta * eta * (u * u + iu))
    # Select the branch with nonnegative real part for numerical stability.
    if d.real < 0:
        d = -d
    g = (b - d) / (b + d)
    exp_dt = cmath.exp(-d * t)

    c = (
        iu * (math.log(spot) + (rate - dividend_yield) * t)
        + (kappa * theta / (eta * eta))
        * (
            (b - d) * t
            - 2.0
            * cmath.log((1.0 - g * exp_dt) / (1.0 - g))
        )
    )
    dcoef = (
        (b - d) / (eta * eta)
        * ((1.0 - exp_dt) / (1.0 - g * exp_dt))
    )
    return cmath.exp(c + dcoef * v0)


def _probability(
    j: int,
    option: VanillaOption,
    params: HestonParameters,
    integration_limit: float,
) -> float:
    log_k = math.log(option.strike)
    common = dict(
        spot=option.spot,
        time_to_expiry=option.time_to_expiry,
        rate=option.rate,
        dividend_yield=option.dividend_yield,
        params=params,
    )
    phi_minus_i = characteristic_function(-1j, **common)

    def integrand(u: float) -> float:
        if u == 0.0:
            u = 1e-12
        if j == 1:
            numerator = characteristic_function(u - 1j, **common)
            denominator = 1j * u * phi_minus_i
        else:
            numerator = characteristic_function(u, **common)
            denominator = 1j * u
        value = cmath.exp(-1j * u * log_k) * numerator / denominator
        return float(value.real)

    integral, _ = quad(
        integrand,
        0.0,
        integration_limit,
        epsabs=1e-8,
        epsrel=1e-7,
        limit=250,
    )
    return 0.5 + integral / math.pi


def price(
    option: VanillaOption,
    params: HestonParameters,
    *,
    integration_limit: float = 120.0,
) -> float:
    option.validate()
    params.validate()
    if integration_limit <= 0:
        raise QuantInputError("integration_limit must be positive")
    if option.time_to_expiry == 0:
        return bsm_price(option)
    if params.vol_of_vol <= 1e-10:
        return bsm_price(
            VanillaOption(
                spot=option.spot,
                strike=option.strike,
                time_to_expiry=option.time_to_expiry,
                rate=option.rate,
                volatility=math.sqrt(params.v0),
                right=option.right,
                dividend_yield=option.dividend_yield,
            )
        )

    p1 = _probability(1, option, params, integration_limit)
    p2 = _probability(2, option, params, integration_limit)
    call = (
        option.spot
        * math.exp(-option.dividend_yield * option.time_to_expiry)
        * p1
        - option.strike
        * math.exp(-option.rate * option.time_to_expiry)
        * p2
    )
    call = max(float(call), 0.0)
    if option.normalized_right() == "CALL":
        return call
    parity = (
        option.strike * math.exp(-option.rate * option.time_to_expiry)
        - option.spot * math.exp(-option.dividend_yield * option.time_to_expiry)
    )
    return max(call + parity, 0.0)


@dataclass(frozen=True)
class HestonCalibrationResult:
    parameters: HestonParameters
    diagnostics: CalibrationDiagnostics

    def as_dict(self) -> dict:
        return {
            "parameters": self.parameters.as_dict(),
            "diagnostics": self.diagnostics.as_dict(),
        }


def calibrate(
    options: Sequence[VanillaOption],
    market_prices: Sequence[float],
    *,
    initial: HestonParameters | None = None,
    max_nfev: int = 80,
    integration_limit: float = 80.0,
) -> HestonCalibrationResult:
    if len(options) != len(market_prices) or len(options) < 5:
        raise QuantInputError("Heston calibration requires >=5 matched observations")
    if any(p <= 0 or not math.isfinite(p) for p in market_prices):
        raise QuantInputError("market prices must be finite and positive")
    for option in options:
        option.validate()
        if option.time_to_expiry <= 0:
            raise QuantInputError("calibration options must be unexpired")

    initial = initial or HestonParameters(
        kappa=1.5,
        theta=0.04,
        vol_of_vol=0.4,
        rho=-0.5,
        v0=0.04,
    )
    initial.validate()
    x0 = np.array([
        initial.kappa,
        initial.theta,
        initial.vol_of_vol,
        initial.rho,
        initial.v0,
    ])
    lower = np.array([0.05, 0.001, 0.01, -0.98, 0.001])
    upper = np.array([10.0, 1.0, 3.0, 0.98, 1.0])
    scales = np.maximum(np.asarray(market_prices, dtype=float), 0.25)

    def residuals(x: np.ndarray) -> np.ndarray:
        p = HestonParameters(*map(float, x))
        model = np.array([
            price(option, p, integration_limit=integration_limit)
            for option in options
        ])
        return (model - np.asarray(market_prices, dtype=float)) / scales

    result = least_squares(
        residuals,
        x0,
        bounds=(lower, upper),
        max_nfev=max_nfev,
        xtol=1e-7,
        ftol=1e-7,
        gtol=1e-7,
    )
    fitted = HestonParameters(*map(float, result.x))
    raw_errors = np.array([
        price(option, fitted, integration_limit=integration_limit) - market
        for option, market in zip(options, market_prices)
    ])
    names = ("kappa", "theta", "vol_of_vol", "rho", "v0")
    boundary_hits = tuple(
        name
        for name, value, lo, hi in zip(names, result.x, lower, upper)
        if abs(value - lo) <= 1e-4 * max(1.0, abs(lo))
        or abs(value - hi) <= 1e-4 * max(1.0, abs(hi))
    )
    diagnostics = CalibrationDiagnostics(
        converged=bool(result.success),
        rmse=float(np.sqrt(np.mean(raw_errors**2))),
        mae=float(np.mean(np.abs(raw_errors))),
        max_abs_error=float(np.max(np.abs(raw_errors))),
        observations=len(options),
        objective=float(np.sum(result.fun**2)),
        message=str(result.message),
        boundary_hits=boundary_hits,
    )
    return HestonCalibrationResult(fitted, diagnostics)
