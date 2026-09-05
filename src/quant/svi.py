from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Sequence

import numpy as np
from scipy.optimize import least_squares

from src.quant.types import CalibrationDiagnostics, QuantInputError


@dataclass(frozen=True)
class SVIParameters:
    a: float
    b: float
    rho: float
    m: float
    sigma: float

    def validate(self) -> None:
        if self.b < 0:
            raise QuantInputError("SVI b cannot be negative")
        if not -1 < self.rho < 1:
            raise QuantInputError("SVI rho must be strictly between -1 and 1")
        if self.sigma <= 0:
            raise QuantInputError("SVI sigma must be positive")

    def as_dict(self) -> dict:
        return asdict(self)


def total_variance(log_moneyness: float | np.ndarray, params: SVIParameters):
    params.validate()
    k = np.asarray(log_moneyness, dtype=float)
    x = k - params.m
    values = params.a + params.b * (
        params.rho * x + np.sqrt(x * x + params.sigma * params.sigma)
    )
    if np.isscalar(log_moneyness):
        return float(values)
    return values


def minimum_total_variance(params: SVIParameters) -> float:
    params.validate()
    return params.a + params.b * params.sigma * math.sqrt(1.0 - params.rho**2)


def sampled_static_arbitrage(
    params: SVIParameters,
    *,
    k_min: float = -1.5,
    k_max: float = 1.5,
    points: int = 601,
) -> dict:
    params.validate()
    if points < 5:
        raise QuantInputError("points must be >=5")
    k = np.linspace(k_min, k_max, points)
    w = total_variance(k, params)
    first = np.gradient(w, k)
    second = np.gradient(first, k)
    return {
        "minimum_total_variance": float(np.min(w)),
        "negative_total_variance": bool(np.any(w < -1e-10)),
        "sampled_min_second_derivative": float(np.min(second)),
        "parameter_minimum_total_variance": float(minimum_total_variance(params)),
    }


@dataclass(frozen=True)
class SVICalibrationResult:
    parameters: SVIParameters
    diagnostics: CalibrationDiagnostics

    def as_dict(self) -> dict:
        return {
            "parameters": self.parameters.as_dict(),
            "diagnostics": self.diagnostics.as_dict(),
        }


def calibrate(
    log_moneyness: Sequence[float],
    implied_volatility: Sequence[float],
    time_to_expiry: float,
    *,
    initial: SVIParameters | None = None,
) -> SVICalibrationResult:
    k = np.asarray(log_moneyness, dtype=float)
    iv = np.asarray(implied_volatility, dtype=float)
    if len(k) != len(iv) or len(k) < 5:
        raise QuantInputError("SVI calibration requires >=5 matched observations")
    if time_to_expiry <= 0:
        raise QuantInputError("time_to_expiry must be positive")
    if np.any(~np.isfinite(k)) or np.any(~np.isfinite(iv)) or np.any(iv <= 0):
        raise QuantInputError("SVI inputs must be finite and IV positive")

    observed_w = iv * iv * time_to_expiry
    initial = initial or SVIParameters(
        a=max(float(np.min(observed_w)) * 0.7, 1e-6),
        b=0.1,
        rho=-0.3,
        m=float(np.median(k)),
        sigma=0.2,
    )
    initial.validate()
    x0 = np.array([initial.a, initial.b, initial.rho, initial.m, initial.sigma])
    lower = np.array([-1.0, 0.0, -0.999, -3.0, 1e-4])
    upper = np.array([5.0, 5.0, 0.999, 3.0, 5.0])

    def residuals(x: np.ndarray) -> np.ndarray:
        params = SVIParameters(*map(float, x))
        fitted = total_variance(k, params)
        penalty = max(0.0, -minimum_total_variance(params)) * 100.0
        if penalty:
            return np.concatenate([fitted - observed_w, np.array([penalty])])
        return np.concatenate([fitted - observed_w, np.array([0.0])])

    result = least_squares(
        residuals,
        x0,
        bounds=(lower, upper),
        max_nfev=5000,
        xtol=1e-12,
        ftol=1e-12,
        gtol=1e-12,
    )
    fitted = SVIParameters(*map(float, result.x))
    errors = total_variance(k, fitted) - observed_w
    names = ("a", "b", "rho", "m", "sigma")
    boundary_hits = tuple(
        name
        for name, value, lo, hi in zip(names, result.x, lower, upper)
        if abs(value - lo) <= 1e-6 * max(1.0, abs(lo))
        or abs(value - hi) <= 1e-6 * max(1.0, abs(hi))
    )
    return SVICalibrationResult(
        parameters=fitted,
        diagnostics=CalibrationDiagnostics(
            converged=bool(result.success) and minimum_total_variance(fitted) >= -1e-10,
            rmse=float(np.sqrt(np.mean(errors**2))),
            mae=float(np.mean(np.abs(errors))),
            max_abs_error=float(np.max(np.abs(errors))),
            observations=len(k),
            objective=float(np.sum(result.fun**2)),
            message=str(result.message),
            boundary_hits=boundary_hits,
        ),
    )
