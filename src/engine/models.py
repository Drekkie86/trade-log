"""Terminal-price distributions for the engine.

Two distributions are built per expiry:

* IMPLIED    - the market's risk-neutral distribution from the whole smile
               (Breeden-Litzenberger on a fitted smile). Under it every structure
               is worth about its market price, skew included: the benchmark.
* REAL_WORLD - the same distribution with its spread around the forward scaled by
               the square root of the underlying's variance risk premium ratio
               lambda = realised variance / implied variance, measured over the
               trailing window on matched 30-day horizons. The smile's shape
               (skew, tails) is kept; only its width changes. lambda < 1 means the
               options have paid more variance than was delivered, which is the
               premium a seller collects; lambda >= 1 means there is nothing to
               sell.

Both distributions are martingales around the forward (E[S_T] = F): the engine
takes no directional view. Every distribution is a deterministic sample of log
returns, so identical inputs always give identical scores.

V1's forecast models (EWMA/GARCH lognormal, resampled history) are gone. On the
first backtest they disagreed with the smile mostly by having no skew, and the
smile was right: see docs/reviews/HOSTILE_REVIEW_ENGINE_V1_2026-11-07.md.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence

import numpy as np
from scipy.stats import norm

IMPLIED = "IMPLIED"
REAL_WORLD = "REAL_WORLD"

FAMILY_MARKET = "OPTIONS_MARKET"
FAMILY_RISK_PREMIUM = "RISK_PREMIUM_ADJUSTED"

GRID_POINTS = 2001
_Z_GRID = norm.ppf((np.arange(GRID_POINTS) + 0.5) / GRID_POINTS)

# Variance risk premium estimation. One year of daily observations is the minimum
# (about twelve independent monthly windows); the window is two years when there
# is that much history. Each observation pairs the 30-calendar-day constant-
# maturity implied variance at a session's close with the realised variance of
# the 21 sessions that followed it.
IV_TARGET_DAYS = 30
IV_NEAREST_TOLERANCE_DAYS = 10     # single-expiry fallback when 30 days is not bracketed
REALISED_HORIZON_SESSIONS = 21
MIN_PREMIUM_OBSERVATIONS = 250
PREMIUM_WINDOW_SESSIONS = 504
TRADING_DAYS_PER_YEAR = 252.0


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
    return np.diff(np.log(c))


# ------------------------------------------------------------------- market
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
    expiry. The market distribution already contains it; the engine uses the
    number to tell the operator that an event is in the window.
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


# ------------------------------------------------------------ risk premium
def constant_maturity_iv(points: Sequence[tuple[float, float]],
                         target_days: int = IV_TARGET_DAYS,
                         nearest_tolerance_days: int = IV_NEAREST_TOLERANCE_DAYS) -> float | None:
    """Implied vol at ``target_days`` from (calendar_years, atm_iv) points.

    Total variance is interpolated linearly in time between the two expiries that
    bracket the target. When the target is not bracketed, the single expiry
    within ``nearest_tolerance_days`` of it is used as is; otherwise None.
    """
    pts = sorted((t, v) for t, v in points
                 if t is not None and v is not None and math.isfinite(t) and math.isfinite(v)
                 and t > 0 and v > 0)
    if not pts:
        return None
    target = target_days / 365.0
    below = [(t, v) for t, v in pts if t <= target]
    above = [(t, v) for t, v in pts if t >= target]
    if below and above:
        t0, v0 = below[-1]
        t1, v1 = above[0]
        if t1 == t0:
            return v0
        w0, w1 = v0 * v0 * t0, v1 * v1 * t1
        w = w0 + (w1 - w0) * (target - t0) / (t1 - t0)
        return math.sqrt(w / target) if w > 0 else None
    t, v = min(pts, key=lambda p: abs(p[0] - target))
    if abs(t - target) * 365.0 <= nearest_tolerance_days:
        return v
    return None


def realised_variances(closes: Sequence[tuple[str, float]],
                       horizon: int = REALISED_HORIZON_SESSIONS) -> dict[str, float]:
    """session_date -> annualised realised variance of the ``horizon`` sessions after it.

    ``closes`` are ascending (session_date, split-adjusted close). Sum of squared
    daily log returns, not demeaned, scaled to a year.
    """
    if len(closes) <= horizon:
        return {}
    dates = [d for d, _ in closes]
    logc = np.log(np.asarray([c for _, c in closes], dtype=float))
    r2 = np.diff(logc) ** 2                       # r2[i] is the return INTO session i+1
    csum = np.concatenate([[0.0], np.cumsum(r2)])
    out: dict[str, float] = {}
    scale = TRADING_DAYS_PER_YEAR / horizon
    for i in range(len(dates) - horizon):
        out[dates[i]] = float((csum[i + horizon] - csum[i]) * scale)
    return out


@dataclass(frozen=True)
class RiskPremium:
    """Trailing variance risk premium of one underlying."""

    ratio: float            # realised variance / implied variance over the window (lambda)
    observations: int
    first_session: str
    last_session: str
    implied_vol: float      # root of the window's mean implied variance, annualised
    realised_vol: float     # root of the window's mean realised variance, annualised

    @property
    def scale(self) -> float:
        """Factor applied to the market distribution's log-return spread."""
        return math.sqrt(self.ratio)

    @property
    def note(self) -> str:
        return (f"lambda {self.ratio:.2f} from {self.observations} sessions "
                f"{self.first_session}..{self.last_session}: options priced "
                f"{self.implied_vol:.1%}, the stock realised {self.realised_vol:.1%}")


def estimate_risk_premium(iv_points: Sequence[tuple[str, float]],
                          closes: Sequence[tuple[str, float]], *, before: str,
                          window: int = PREMIUM_WINDOW_SESSIONS,
                          min_observations: int = MIN_PREMIUM_OBSERVATIONS,
                          horizon: int = REALISED_HORIZON_SESSIONS) -> RiskPremium:
    """lambda = sum(realised variance) / sum(implied variance) over matched sessions.

    ``iv_points`` are (session_date, 30-day constant-maturity implied vol), any
    order. A session counts when its realised window of ``horizon`` sessions is
    complete and ends strictly before ``before``; the newest ``window`` sessions
    are used. Raises ModelUnavailable below ``min_observations``.
    """
    dates = sorted(d for d, _ in closes)
    if len(dates) <= horizon:
        raise ModelUnavailable("RISK_PREMIUM: not enough closes for a realised window")
    realised = realised_variances(sorted(closes), horizon)
    index = {d: i for i, d in enumerate(dates)}
    usable: list[tuple[str, float, float]] = []
    for day, iv in iv_points:
        if iv is None or not math.isfinite(iv) or iv <= 0 or day not in realised:
            continue
        end = dates[index[day] + horizon]
        if end >= before:
            continue
        usable.append((day, iv * iv, realised[day]))
    usable.sort()
    usable = usable[-window:]
    if len(usable) < min_observations:
        raise ModelUnavailable(
            f"RISK_PREMIUM: {len(usable)} matched sessions, need {min_observations}")
    implied_sum = sum(w for _, w, _ in usable)
    realised_sum = sum(rv for _, _, rv in usable)
    if implied_sum <= 0 or realised_sum <= 0:
        raise ModelUnavailable("RISK_PREMIUM: degenerate variance sums")
    n = len(usable)
    return RiskPremium(ratio=realised_sum / implied_sum, observations=n,
                       first_session=usable[0][0], last_session=usable[-1][0],
                       implied_vol=math.sqrt(implied_sum / n),
                       realised_vol=math.sqrt(realised_sum / n))


def real_world_distribution(market: Distribution, premium: RiskPremium) -> Distribution:
    """The market distribution with its spread scaled by sqrt(lambda), re-centred
    on the forward. Skew and tail shape are the market's; only the width changes."""
    if not math.isfinite(premium.ratio) or premium.ratio <= 0:
        raise ModelUnavailable("REAL_WORLD: non-positive risk premium ratio")
    r = market.log_returns
    mu = float(np.mean(r))
    scaled = mu + premium.scale * (r - mu)
    adjusted = _martingale(scaled)
    return Distribution(REAL_WORLD, FAMILY_RISK_PREMIUM, adjusted, float(np.var(adjusted)),
                        premium.note)
