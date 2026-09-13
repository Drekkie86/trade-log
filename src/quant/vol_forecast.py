from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Sequence

import numpy as np
from scipy.optimize import minimize

from src.quant.types import QuantInputError


@dataclass(frozen=True)
class GARCH11Fit:
    omega: float
    alpha: float
    beta: float
    unconditional_variance: float
    last_variance: float
    next_variance: float
    converged: bool
    log_likelihood: float
    message: str

    def as_dict(self) -> dict:
        return asdict(self)


def _garch_parameters_from_unconstrained(x: Sequence[float]) -> tuple[float, float, float]:
    """Map unconstrained optimizer coordinates to stationary GARCH parameters."""
    if len(x) != 3:
        raise QuantInputError("GARCH parameter transform requires exactly three coordinates")
    coords = np.asarray(x, dtype=float)
    if np.any(~np.isfinite(coords)):
        raise QuantInputError("GARCH parameter transform requires finite coordinates")

    try:
        omega = math.exp(float(coords[0]))
    except OverflowError:
        omega = math.inf

    alpha_logit = float(coords[1])
    beta_logit = float(coords[2])
    max_logit = max(0.0, alpha_logit, beta_logit)
    anchor = math.exp(-max_logit)
    a_raw = math.exp(alpha_logit - max_logit)
    b_raw = math.exp(beta_logit - max_logit)
    denom = anchor + a_raw + b_raw
    alpha = 0.999 * a_raw / denom
    beta = 0.999 * b_raw / denom
    return omega, alpha, beta


def require_usable_garch_fit(fit: GARCH11Fit) -> GARCH11Fit:
    """Fail closed before a fitted GARCH model is used as research evidence."""
    if not fit.converged:
        raise QuantInputError(
            f"GARCH(1,1) optimizer did not converge: {fit.message or 'no optimizer message'}"
        )
    numeric = (
        fit.omega,
        fit.alpha,
        fit.beta,
        fit.unconditional_variance,
        fit.last_variance,
        fit.next_variance,
        fit.log_likelihood,
    )
    if any(not math.isfinite(float(value)) for value in numeric):
        raise QuantInputError("GARCH(1,1) fit contains non-finite diagnostics")
    if fit.omega <= 0 or fit.unconditional_variance <= 0 or fit.last_variance <= 0 or fit.next_variance <= 0:
        raise QuantInputError("GARCH(1,1) fit contains non-positive variance parameters")
    if not (0 <= fit.alpha < 1 and 0 <= fit.beta < 1 and fit.alpha + fit.beta < 0.999):
        raise QuantInputError("GARCH(1,1) fit violates the stationary parameter contract")
    return fit


def ewma_variance(
    returns: Sequence[float],
    *,
    decay: float = 0.94,
    initial_variance: float | None = None,
) -> float:
    r = np.asarray(returns, dtype=float)
    if len(r) < 2 or np.any(~np.isfinite(r)):
        raise QuantInputError("EWMA requires >=2 finite returns")
    if not 0 < decay < 1:
        raise QuantInputError("decay must be between 0 and 1")
    variance = float(np.var(r, ddof=1) if initial_variance is None else initial_variance)
    if variance < 0:
        raise QuantInputError("initial_variance cannot be negative")
    for value in r:
        variance = decay * variance + (1.0 - decay) * float(value * value)
    return float(variance)


def fit_garch11(returns: Sequence[float]) -> GARCH11Fit:
    r = np.asarray(returns, dtype=float)
    if len(r) < 30 or np.any(~np.isfinite(r)):
        raise QuantInputError("GARCH(1,1) requires >=30 finite returns")
    sample_var = max(float(np.var(r, ddof=1)), 1e-12)

    def unpack(x: np.ndarray) -> tuple[float, float, float]:
        return _garch_parameters_from_unconstrained(x)

    def variance_path(omega: float, alpha: float, beta: float) -> np.ndarray:
        var = np.empty_like(r)
        var[0] = sample_var
        for i in range(1, len(r)):
            var[i] = omega + alpha * r[i - 1] ** 2 + beta * var[i - 1]
            if var[i] <= 1e-18 or not math.isfinite(float(var[i])):
                var[i] = 1e-18
        return var

    def objective(x: np.ndarray) -> float:
        omega, alpha, beta = unpack(x)
        if not math.isfinite(omega) or omega <= 0:
            return math.inf
        var = variance_path(omega, alpha, beta)
        ll = -0.5 * np.sum(np.log(2.0 * math.pi) + np.log(var) + (r * r) / var)
        return float(-ll)

    alpha0, beta0 = 0.06, 0.90
    omega0 = max(sample_var * (1.0 - alpha0 - beta0), 1e-12)
    x0 = np.array([
        math.log(omega0),
        math.log(alpha0 / (0.999 - alpha0 - beta0)),
        math.log(beta0 / (0.999 - alpha0 - beta0)),
    ])
    result = minimize(objective, x0, method="L-BFGS-B")
    omega, alpha, beta = unpack(result.x)
    var = variance_path(omega, alpha, beta)
    next_var = omega + alpha * r[-1] ** 2 + beta * var[-1]
    unconditional = omega / max(1.0 - alpha - beta, 1e-12)
    return GARCH11Fit(
        omega=float(omega),
        alpha=float(alpha),
        beta=float(beta),
        unconditional_variance=float(unconditional),
        last_variance=float(var[-1]),
        next_variance=float(next_var),
        converged=bool(result.success),
        log_likelihood=float(-result.fun),
        message=str(result.message),
    )
