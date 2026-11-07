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

MIN_RETURNS_FOR_VOL = 250          # a year of daily returns; GARCH on less is noise
MIN_WINDOWS_FOR_EMPIRICAL = 200
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
    """Lognormal at the ATM implied volatility: the market view without its skew."""
    if not (math.isfinite(atm_iv) and atm_iv > 0 and calendar_years > 0):
        raise ModelUnavailable("IMPLIED: no usable ATM implied volatility")
    return lognormal(IMPLIED, FAMILY_MARKET, atm_iv * atm_iv * calendar_years, "ATM volatility, no skew")


SMILE_MIN_POINTS = 5
SMILE_GRID = 1201
SMILE_RANGE_SD = 6.0


def smile_implied_distribution(points: Sequence[tuple[float, float]], atm_iv: float,
                               calendar_years: float, rate: float = 0.04) -> Distribution:
    """Risk-neutral terminal distribution from the whole smile (Breeden-Litzenberger).

    ``points`` are (log-moneyness ln(K/F), implied vol) of out-of-the-money quotes.
    A quadratic smile in log-moneyness is fitted, call prices are computed on a
    fine strike grid and twice differenced into a density. Under this
    distribution every structure is worth about its market price, skew
    included, so selling expensive puts is no longer "free" in the market view.
    Falls back to the ATM lognormal when the smile cannot be fitted.
    """
    T = calendar_years
    if not (math.isfinite(atm_iv) and atm_iv > 0 and T > 0):
        raise ModelUnavailable("IMPLIED: no usable ATM implied volatility")
    pts = [(m, v) for m, v in points if math.isfinite(m) and math.isfinite(v) and 0.02 < v < 3.0]
    lo_side = sum(1 for m, _ in pts if m < 0)
    hi_side = sum(1 for m, _ in pts if m > 0)
    if len(pts) < SMILE_MIN_POINTS or lo_side < 2 or hi_side < 2:
        return implied_distribution(atm_iv, T)
    m = np.array([p[0] for p in pts])
    v = np.array([p[1] for p in pts])
    # Quadratic in log-moneyness, least squares; weights favour near-the-money points.
    w = np.exp(-(m / (2.0 * atm_iv * math.sqrt(T) + 1e-9)) ** 2)
    A = np.vstack([np.ones_like(m), m, m * m]).T * w[:, None]
    coef, *_ = np.linalg.lstsq(A, v * w, rcond=None)
    sd = atm_iv * math.sqrt(T)
    grid_m = np.linspace(-SMILE_RANGE_SD * sd, SMILE_RANGE_SD * sd, SMILE_GRID)
    iv = np.clip(coef[0] + coef[1] * grid_m + coef[2] * grid_m * grid_m, 0.5 * atm_iv, 4.0 * atm_iv)
    # Black-76 calls on the grid with forward 1 (log-moneyness is strike).
    K = np.exp(grid_m)
    s = iv * math.sqrt(T)
    d1 = (-grid_m + 0.5 * s * s) / s
    d2 = d1 - s
    calls = norm.cdf(d1) - K * norm.cdf(d2)
    density = np.gradient(np.gradient(calls, K), K)
    density = np.clip(density, 0.0, None)
    mass = np.trapezoid(density, K) if hasattr(np, "trapezoid") else np.trapz(density, K)
    if not math.isfinite(mass) or mass < 0.9:
        return implied_distribution(atm_iv, T)
    density = density / mass
    cdf = np.cumsum((density[1:] + density[:-1]) * 0.5 * np.diff(K))
    cdf = np.concatenate([[0.0], cdf]) / cdf[-1]
    probs = (np.arange(GRID_POINTS) + 0.5) / GRID_POINTS
    sample_k = np.interp(probs, cdf, K)
    r = np.log(sample_k)
    var = float(np.var(r))
    if not math.isfinite(var) or var <= 0:
        return implied_distribution(atm_iv, T)
    return Distribution(IMPLIED, FAMILY_MARKET, _martingale(r), var,
                        f"smile from {len(pts)} strikes")


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
