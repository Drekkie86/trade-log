"""Terminal-price distributions for the engine.

Three distributions are built per underlying and horizon:

* IMPLIED   - lognormal at the expiry's ATM implied volatility. Under this
              view every structure is worth roughly minus its costs, so it is
              the benchmark to beat, never a vote.
* VOL_FORECAST - lognormal at a forecast of realised volatility
              (EWMA and GARCH(1,1) blended) from the stock's own history.
* EMPIRICAL - resampled historical h-day log returns (fat tails, skew).

VOL_FORECAST and EMPIRICAL share one information source (the price history),
so they form ONE evidence family. The engine scores a trade by the worse of
the two: agreement shows robustness to the tail assumption, not a second,
independent confirmation.

All distributions are martingales around the forward (E[S_T] = F): the engine
takes no directional drift view. Any edge must come from volatility and
distribution shape, not from a bullish or bearish assumption.

Every distribution is a deterministic sample of log returns (quantile grid or
historical windows), so identical inputs always give identical scores.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence

import numpy as np
from scipy.stats import norm

from src.quant.types import QuantInputError
from src.quant.vol_forecast import ewma_variance, fit_garch11, require_usable_garch_fit

IMPLIED = "IMPLIED"
VOL_FORECAST = "VOL_FORECAST"
EMPIRICAL = "EMPIRICAL"

FAMILY_MARKET = "OPTIONS_MARKET"
FAMILY_PRICE_HISTORY = "PRICE_HISTORY"

GRID_POINTS = 2001
_Z_GRID = norm.ppf((np.arange(GRID_POINTS) + 0.5) / GRID_POINTS)

MIN_RETURNS_FOR_VOL = 60
MIN_WINDOWS_FOR_EMPIRICAL = 60
MAX_HISTORY_RETURNS = 504
EWMA_DECAY = 0.94


class ModelUnavailable(ValueError):
    """A model cannot be built honestly from the available inputs."""


@dataclass(frozen=True)
class Distribution:
    model_id: str
    family: str
    log_returns: np.ndarray = field(repr=False)
    horizon_variance: float
    note: str = ""

    def terminal_prices(self, forward: float) -> np.ndarray:
        return forward * np.exp(self.log_returns)


def _martingale(log_returns: np.ndarray) -> np.ndarray:
    """Shift so that E[exp(r)] = 1 exactly on this sample."""
    shift = math.log(float(np.mean(np.exp(log_returns))))
    return log_returns - shift


def lognormal(model_id: str, family: str, horizon_variance: float, note: str = "") -> Distribution:
    if not math.isfinite(horizon_variance) or horizon_variance <= 0:
        raise ModelUnavailable(f"{model_id}: non-positive horizon variance")
    sigma = math.sqrt(horizon_variance)
    r = -0.5 * horizon_variance + sigma * _Z_GRID
    return Distribution(model_id, family, _martingale(r), horizon_variance, note)


def daily_log_returns(closes: Sequence[float]) -> np.ndarray:
    c = np.asarray(closes, dtype=float)
    if c.ndim != 1 or len(c) < 2 or np.any(~np.isfinite(c)) or np.any(c <= 0):
        raise ModelUnavailable("closes must be positive and finite")
    r = np.diff(np.log(c))
    return r[-MAX_HISTORY_RETURNS:]


@dataclass(frozen=True)
class VolForecast:
    """Daily-variance forecast fitted once per underlying, applied per horizon."""

    daily_variance_ewma: float
    garch_unconditional: float | None = None
    garch_next: float | None = None
    garch_persistence: float | None = None

    @property
    def note(self) -> str:
        return "EWMA only" if self.garch_next is None else "EWMA + GARCH(1,1) blend"

    @property
    def annualized_vol(self) -> float:
        """One-month forecast expressed as an annualised volatility."""
        return math.sqrt(self.horizon_variance(21.0) / 21.0 * 252.0)

    def horizon_variance(self, trading_days: float) -> float:
        ewma_h = self.daily_variance_ewma * trading_days
        if self.garch_next is None:
            return ewma_h
        steps = max(1, int(math.ceil(trading_days)))
        # Sum of k-step-ahead variances, scaled to a fractional horizon.
        total = sum(
            self.garch_unconditional
            + self.garch_persistence ** (k - 1) * (self.garch_next - self.garch_unconditional)
            for k in range(1, steps + 1)
        )
        return 0.5 * (ewma_h + float(total) * (trading_days / steps))


def forecast_volatility(returns: np.ndarray) -> VolForecast:
    if len(returns) < MIN_RETURNS_FOR_VOL:
        raise ModelUnavailable(
            f"VOL_FORECAST: {len(returns)} daily returns, need {MIN_RETURNS_FOR_VOL}"
        )
    try:
        ewma = ewma_variance(returns, decay=EWMA_DECAY)
    except QuantInputError as exc:
        raise ModelUnavailable(f"VOL_FORECAST: {exc}") from exc
    try:
        fit = require_usable_garch_fit(fit_garch11(returns))
    except (QuantInputError, ValueError, FloatingPointError):
        return VolForecast(float(ewma))
    return VolForecast(float(ewma), fit.unconditional_variance, fit.next_variance,
                       fit.alpha + fit.beta)


def vol_forecast_distribution(
    forecast: VolForecast, trading_days: float, event_variance: float = 0.0
) -> Distribution:
    v = forecast.horizon_variance(trading_days) + max(0.0, event_variance)
    return lognormal(VOL_FORECAST, FAMILY_PRICE_HISTORY, v, forecast.note)


def empirical_distribution(
    closes: Sequence[float], trading_days: float, event_variance: float = 0.0
) -> Distribution:
    """Overlapping historical h-day returns, demeaned, optionally event-widened.

    For a horizon under one trading day (0DTE) the one-day returns are scaled
    by sqrt(fraction): the shape is historical, the scaling is an assumption.
    """
    c = np.asarray(closes, dtype=float)[-(MAX_HISTORY_RETURNS + 1):]
    logc = np.log(c)
    if trading_days < 1.0:
        windows = np.diff(logc) * math.sqrt(max(trading_days, 1e-6))
        note = "1-day historical returns scaled to the remaining session"
    else:
        h = int(round(trading_days))
        if len(logc) <= h:
            raise ModelUnavailable("EMPIRICAL: history shorter than horizon")
        windows = logc[h:] - logc[:-h]
        note = f"{len(windows)} overlapping {h}-day historical windows"
    if len(windows) < MIN_WINDOWS_FOR_EMPIRICAL:
        raise ModelUnavailable(
            f"EMPIRICAL: {len(windows)} windows, need {MIN_WINDOWS_FOR_EMPIRICAL}"
        )
    w = windows - float(np.mean(windows))
    var = float(np.var(w))
    if var <= 0:
        raise ModelUnavailable("EMPIRICAL: zero variance history")
    if event_variance > 0:
        w = w * math.sqrt((var + event_variance) / var)
        note += "; widened for an implied event"
    w = np.sort(_martingale(w))
    return Distribution(EMPIRICAL, FAMILY_PRICE_HISTORY, w, float(np.var(w)), note)


def implied_distribution(atm_iv: float, calendar_years: float) -> Distribution:
    if not (math.isfinite(atm_iv) and atm_iv > 0 and calendar_years > 0):
        raise ModelUnavailable("IMPLIED: no usable ATM implied volatility")
    return lognormal(IMPLIED, FAMILY_MARKET, atm_iv * atm_iv * calendar_years)


def implied_event_variance(
    expiries: Sequence[tuple[float, float]], threshold: float = 1.8
) -> list[float]:
    """Cumulative event variance per expiry from the ATM term structure.

    ``expiries`` is ordered (calendar_years, atm_iv). A forward-variance
    interval far above the chain's median forward rate is treated as a priced
    event (earnings, macro); its excess total variance is added to every later
    expiry. Forecast models ignore jumps, so without this they would call
    selling premium into earnings free money.
    """
    if not expiries:
        return []
    prev_t, prev_w = 0.0, 0.0
    rates: list[float] = []
    dts: list[float] = []
    for t, iv in expiries:
        w = iv * iv * t
        dt = t - prev_t
        if dt <= 0:
            rates.append(float("nan"))
            dts.append(0.0)
        else:
            rates.append(max(0.0, (w - prev_w) / dt))
            dts.append(dt)
        prev_t, prev_w = t, w
    finite = [r for r in rates if math.isfinite(r)]
    if len(finite) < 3:
        return [0.0] * len(expiries)
    base = float(np.median(finite))
    cumulative, out = 0.0, []
    for r, dt in zip(rates, dts):
        if math.isfinite(r) and base > 0 and r > threshold * base:
            cumulative += (r - base) * dt
        out.append(cumulative)
    return out
