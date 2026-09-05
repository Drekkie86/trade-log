from __future__ import annotations

import math
from typing import Sequence

import numpy as np

from src.quant.types import QuantInputError


def _positive_array(values: Sequence[float], name: str) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    if len(arr) < 2 or np.any(~np.isfinite(arr)) or np.any(arr <= 0):
        raise QuantInputError(f"{name} must contain >=2 finite positive values")
    return arr


def close_to_close(closes: Sequence[float], *, annualization: float = 252.0) -> float:
    c = _positive_array(closes, "closes")
    if annualization <= 0:
        raise QuantInputError("annualization must be positive")
    returns = np.diff(np.log(c))
    if len(returns) < 2:
        return 0.0
    return float(np.std(returns, ddof=1) * math.sqrt(annualization))


def parkinson(highs: Sequence[float], lows: Sequence[float], *, annualization: float = 252.0) -> float:
    h = _positive_array(highs, "highs")
    l = _positive_array(lows, "lows")
    if len(h) != len(l) or np.any(h < l):
        raise QuantInputError("highs/lows must be matched and high >= low")
    variance = np.mean(np.log(h / l) ** 2) / (4.0 * math.log(2.0))
    return float(math.sqrt(max(variance * annualization, 0.0)))


def garman_klass(
    opens: Sequence[float], highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], *, annualization: float = 252.0
) -> float:
    o = _positive_array(opens, "opens")
    h = _positive_array(highs, "highs")
    l = _positive_array(lows, "lows")
    c = _positive_array(closes, "closes")
    if not (len(o) == len(h) == len(l) == len(c)):
        raise QuantInputError("OHLC arrays must have equal lengths")
    if np.any(h < np.maximum(o, c)) or np.any(l > np.minimum(o, c)):
        raise QuantInputError("OHLC ranges are inconsistent")
    term = 0.5 * np.log(h / l) ** 2 - (2.0 * math.log(2.0) - 1.0) * np.log(c / o) ** 2
    return float(math.sqrt(max(float(np.mean(term)) * annualization, 0.0)))


def rogers_satchell(
    opens: Sequence[float], highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], *, annualization: float = 252.0
) -> float:
    o = _positive_array(opens, "opens")
    h = _positive_array(highs, "highs")
    l = _positive_array(lows, "lows")
    c = _positive_array(closes, "closes")
    if not (len(o) == len(h) == len(l) == len(c)):
        raise QuantInputError("OHLC arrays must have equal lengths")
    rs = np.log(h / o) * np.log(h / c) + np.log(l / o) * np.log(l / c)
    return float(math.sqrt(max(float(np.mean(rs)) * annualization, 0.0)))


def yang_zhang(
    opens: Sequence[float], highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], *, annualization: float = 252.0
) -> float:
    o = _positive_array(opens, "opens")
    h = _positive_array(highs, "highs")
    l = _positive_array(lows, "lows")
    c = _positive_array(closes, "closes")
    n = len(c)
    if n < 3 or not (len(o) == len(h) == len(l) == n):
        raise QuantInputError("Yang-Zhang requires >=3 matched OHLC observations")
    overnight = np.log(o[1:] / c[:-1])
    open_close = np.log(c / o)
    rs = np.log(h / o) * np.log(h / c) + np.log(l / o) * np.log(l / c)
    var_o = float(np.var(overnight, ddof=1))
    var_c = float(np.var(open_close, ddof=1))
    rs_mean = float(np.mean(rs))
    k = 0.34 / (1.34 + (n + 1.0) / (n - 1.0))
    variance = var_o + k * var_c + (1.0 - k) * rs_mean
    return float(math.sqrt(max(variance * annualization, 0.0)))
