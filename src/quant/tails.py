from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Sequence

import numpy as np
from scipy.stats import kurtosis, skew

from src.quant.types import QuantInputError


@dataclass(frozen=True)
class TailDiagnostics:
    observations: int
    mean: float
    standard_deviation: float
    skewness: float
    excess_kurtosis: float
    var_95: float
    cvar_95: float
    var_99: float
    cvar_99: float
    hill_tail_index: float | None

    def as_dict(self) -> dict:
        return asdict(self)


def _var_cvar(losses: np.ndarray, level: float) -> tuple[float, float]:
    var = float(np.quantile(losses, level))
    tail = losses[losses >= var]
    return var, float(np.mean(tail)) if len(tail) else var


def hill_tail_index(losses: Sequence[float], *, tail_fraction: float = 0.1) -> float | None:
    x = np.asarray(losses, dtype=float)
    x = x[np.isfinite(x) & (x > 0)]
    if len(x) < 20 or not 0 < tail_fraction < 0.5:
        return None
    x = np.sort(x)
    k = max(5, int(len(x) * tail_fraction))
    threshold = x[-k - 1]
    top = x[-k:]
    if threshold <= 0:
        return None
    gamma = float(np.mean(np.log(top / threshold)))
    if gamma <= 0:
        return None
    return 1.0 / gamma


def diagnose(returns: Sequence[float]) -> TailDiagnostics:
    r = np.asarray(returns, dtype=float)
    if len(r) < 20 or np.any(~np.isfinite(r)):
        raise QuantInputError("tail diagnostics require >=20 finite returns")
    losses = -r
    var95, cvar95 = _var_cvar(losses, 0.95)
    var99, cvar99 = _var_cvar(losses, 0.99)
    return TailDiagnostics(
        observations=len(r),
        mean=float(np.mean(r)),
        standard_deviation=float(np.std(r, ddof=1)),
        skewness=float(skew(r, bias=False)),
        excess_kurtosis=float(kurtosis(r, fisher=True, bias=False)),
        var_95=var95,
        cvar_95=cvar95,
        var_99=var99,
        cvar_99=cvar99,
        hill_tail_index=hill_tail_index(losses),
    )
