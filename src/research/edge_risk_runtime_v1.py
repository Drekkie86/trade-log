from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
import math
from pathlib import Path
from statistics import median
from typing import Any

import numpy as np

from src.database.repository import resolve_db_path
from src.operations.sqlite_runtime import open_readonly_connection
from src.quant.forecast_validation import tournament
from src.quant.rolling_variance_forecast import (
    EWMA_MODEL_ID,
    GARCH11_MODEL_ID,
    HISTORICAL_VARIANCE_MODEL_ID,
    RollingForecastConfig,
    rolling_variance_forecasts,
)
from src.quant.vol_forecast import ewma_variance, fit_garch11
from src.research.edge_library_v1 import edge_registry, variance_gap_diagnostic


RUNTIME_VERSION = "1.0.0"


@dataclass(frozen=True)
class EdgeRuntimeObservation:
    underlying: str
    state: str
    detail: str
    session_price_count: int
    return_count: int
    forecast_model_id: str | None
    forecast_daily_variance: float | None
    matched_expiration: str | None
    matched_dte: int | None
    surface_median_iv: float | None
    variance_gap: dict[str, Any] | None


@dataclass(frozen=True)
class EdgeRiskRuntime:
    version: str
    state: str
    observations: tuple[EdgeRuntimeObservation, ...]
    edge_library: tuple[dict[str, Any], ...]
    decision_authority: str
    family_activation_authority: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "state": self.state,
            "observations": [asdict(item) for item in self.observations],
            "edge_library": list(self.edge_library),
            "decision_authority": self.decision_authority,
            "family_activation_authority": self.family_activation_authority,
        }


def _session_prices(conn, *, limit_underlyings: int) -> dict[str, list[float]]:
    rows = conn.execute(
        """
        WITH ranked AS (
            SELECT
                underlying,
                us_session_date,
                underlying_price,
                captured_at,
                ROW_NUMBER() OVER (
                    PARTITION BY underlying, us_session_date
                    ORDER BY captured_at DESC, id DESC
                ) AS rn
            FROM market_snapshots
            WHERE underlying_price IS NOT NULL
              AND underlying_price > 0
              AND us_session_date IS NOT NULL
              AND us_session_state IN ('INTRADAY', 'POST_CLOSE')
        ), symbols AS (
            SELECT underlying, COUNT(*) AS n
            FROM ranked
            WHERE rn = 1
            GROUP BY underlying
            ORDER BY n DESC, underlying
            LIMIT ?
        )
        SELECT r.underlying, r.underlying_price
        FROM ranked AS r
        JOIN symbols AS s ON s.underlying = r.underlying
        WHERE r.rn = 1
        ORDER BY r.underlying, r.us_session_date;
        """,
        (limit_underlyings,),
    ).fetchall()
    result: dict[str, list[float]] = {}
    for row in rows:
        result.setdefault(str(row["underlying"]), []).append(float(row["underlying_price"]))
    return result


def _log_returns(prices: list[float]) -> np.ndarray:
    if len(prices) < 2:
        return np.asarray([], dtype=float)
    values = np.asarray(prices, dtype=float)
    if np.any(~np.isfinite(values)) or np.any(values <= 0):
        return np.asarray([], dtype=float)
    return np.diff(np.log(values))


def _garch_horizon_average(fit, *, horizon_days: int) -> float:
    persistence = fit.alpha + fit.beta
    value = float(fit.next_variance)
    path: list[float] = []
    for _ in range(horizon_days):
        path.append(value)
        value = fit.omega + persistence * value
    return float(np.mean(path))


def _current_forecast(
    returns: np.ndarray,
    *,
    model_id: str,
    train_window: int,
    horizon_days: int,
    ewma_decay: float,
) -> float:
    training = returns[-train_window:]
    if model_id == HISTORICAL_VARIANCE_MODEL_ID:
        return max(float(np.var(training, ddof=1)), float(np.finfo(float).tiny))
    if model_id == EWMA_MODEL_ID:
        return max(float(ewma_variance(training, decay=ewma_decay)), float(np.finfo(float).tiny))
    if model_id == GARCH11_MODEL_ID:
        fit = fit_garch11(training)
        return max(_garch_horizon_average(fit, horizon_days=horizon_days), float(np.finfo(float).tiny))
    raise ValueError(f"unsupported forecast model: {model_id}")


def _forecast_error_std(rows, *, model_id: str) -> float | None:
    errors = [
        float(item.forecast_variance - item.realized_variance)
        for item in rows
        if item.model_id == model_id
    ]
    if len(errors) < 2:
        return None
    value = float(np.std(np.asarray(errors, dtype=float), ddof=1))
    return value if math.isfinite(value) and value > 0 else None


def _matched_surface_iv(conn, *, underlying: str, horizon_days: int) -> tuple[str | None, int | None, float | None]:
    key = conn.execute(
        """
        SELECT research_run_id, us_session_date, underlying_price
        FROM market_snapshots
        WHERE underlying = ?
          AND research_run_id IS NOT NULL
          AND us_session_date IS NOT NULL
          AND underlying_price IS NOT NULL
          AND underlying_price > 0
        ORDER BY research_run_id DESC, captured_at DESC, id DESC
        LIMIT 1;
        """,
        (underlying,),
    ).fetchone()
    if key is None:
        return None, None, None

    session_date = date.fromisoformat(str(key["us_session_date"]))
    spot = float(key["underlying_price"])
    rows = conn.execute(
        """
        SELECT oq.expiration, oq.strike, pmo.implied_volatility
        FROM option_quotes AS oq
        JOIN market_snapshots AS ms ON ms.id = oq.snapshot_id
        JOIN provider_model_observations AS pmo
          ON pmo.option_quote_id = oq.id
         AND pmo.provider = 'THETADATA'
        WHERE ms.research_run_id = ?
          AND ms.underlying = ?
          AND pmo.implied_volatility IS NOT NULL
          AND pmo.implied_volatility > 0
        ORDER BY oq.expiration, oq.strike;
        """,
        (int(key["research_run_id"]), underlying),
    ).fetchall()

    buckets: dict[str, list[float]] = {}
    for row in rows:
        strike = float(row["strike"])
        if not 0.90 * spot <= strike <= 1.10 * spot:
            continue
        expiration = str(row["expiration"])
        try:
            dte = (date.fromisoformat(expiration) - session_date).days
        except ValueError:
            continue
        if dte < 0:
            continue
        buckets.setdefault(expiration, []).append(float(row["implied_volatility"]))

    if not buckets:
        return None, None, None
    expiration = min(
        buckets,
        key=lambda item: (abs((date.fromisoformat(item) - session_date).days - horizon_days), item),
    )
    dte = (date.fromisoformat(expiration) - session_date).days
    return expiration, dte, float(median(buckets[expiration]))


def load_edge_risk_runtime(
    db_path: str | Path | None = None,
    *,
    train_window: int = 40,
    horizon_days: int = 5,
    limit_underlyings: int = 8,
    bootstrap_samples: int = 500,
) -> EdgeRiskRuntime:
    path = resolve_db_path(db_path)
    library = tuple(item.as_dict() for item in edge_registry())
    if not path.exists():
        return EdgeRiskRuntime(
            version=RUNTIME_VERSION,
            state="DATABASE_UNAVAILABLE",
            observations=(),
            edge_library=library,
            decision_authority="NONE_RESEARCH_ONLY",
            family_activation_authority="NONE_PROGRAMME_BUDGET_UNFROZEN",
        )

    config = RollingForecastConfig(train_window=train_window, horizon_days=horizon_days, include_garch=True)
    required_returns = train_window + horizon_days
    conn = open_readonly_connection(path)
    try:
        price_map = _session_prices(conn, limit_underlyings=limit_underlyings)
        observations: list[EdgeRuntimeObservation] = []
        for underlying, prices in price_map.items():
            returns = _log_returns(prices)
            if len(returns) < required_returns:
                observations.append(
                    EdgeRuntimeObservation(
                        underlying=underlying,
                        state="ACCUMULATING_HISTORY",
                        detail=f"Need at least {required_returns} returns; have {len(returns)}.",
                        session_price_count=len(prices),
                        return_count=len(returns),
                        forecast_model_id=None,
                        forecast_daily_variance=None,
                        matched_expiration=None,
                        matched_dte=None,
                        surface_median_iv=None,
                        variance_gap=None,
                    )
                )
                continue

            rows = rolling_variance_forecasts(returns, config=config)
            ranked = tournament(rows, scoring_rule="QLIKE", bootstrap_samples=bootstrap_samples)
            winner = ranked.winner
            if winner is None:
                observations.append(
                    EdgeRuntimeObservation(
                        underlying=underlying,
                        state="NO_FORECAST_WINNER",
                        detail="Forecast tournament has no comparable winner.",
                        session_price_count=len(prices),
                        return_count=len(returns),
                        forecast_model_id=None,
                        forecast_daily_variance=None,
                        matched_expiration=None,
                        matched_dte=None,
                        surface_median_iv=None,
                        variance_gap=None,
                    )
                )
                continue

            forecast_variance = _current_forecast(
                returns,
                model_id=winner,
                train_window=train_window,
                horizon_days=horizon_days,
                ewma_decay=config.ewma_decay,
            )
            error_std = _forecast_error_std(rows, model_id=winner)
            expiration, dte, iv = _matched_surface_iv(
                conn,
                underlying=underlying,
                horizon_days=horizon_days,
            )
            if iv is None:
                observations.append(
                    EdgeRuntimeObservation(
                        underlying=underlying,
                        state="FORECAST_AVAILABLE_IV_UNMATCHED",
                        detail="Forecast is available but no approximately horizon-matched near-spot IV slice is available.",
                        session_price_count=len(prices),
                        return_count=len(returns),
                        forecast_model_id=winner,
                        forecast_daily_variance=forecast_variance,
                        matched_expiration=None,
                        matched_dte=None,
                        surface_median_iv=None,
                        variance_gap=None,
                    )
                )
                continue

            diagnostic = variance_gap_diagnostic(
                implied_volatility_annualized=iv,
                forecast_daily_variance=forecast_variance,
                forecast_error_std_daily_variance=error_std,
            )
            observations.append(
                EdgeRuntimeObservation(
                    underlying=underlying,
                    state="IV_FORECAST_RV_DIAGNOSTIC_AVAILABLE",
                    detail=(
                        "Descriptive diagnostic only: near-spot median IV is matched to the closest available "
                        "expiration, then compared with the historically best QLIKE forecast model."
                    ),
                    session_price_count=len(prices),
                    return_count=len(returns),
                    forecast_model_id=winner,
                    forecast_daily_variance=forecast_variance,
                    matched_expiration=expiration,
                    matched_dte=dte,
                    surface_median_iv=iv,
                    variance_gap=diagnostic.as_dict(),
                )
            )
    finally:
        conn.close()

    if any(item.state == "IV_FORECAST_RV_DIAGNOSTIC_AVAILABLE" for item in observations):
        state = "RESEARCH_DIAGNOSTICS_AVAILABLE"
    elif observations:
        state = "ACCUMULATING_EVIDENCE"
    else:
        state = "NO_RESEARCH_DATA"

    return EdgeRiskRuntime(
        version=RUNTIME_VERSION,
        state=state,
        observations=tuple(observations),
        edge_library=library,
        decision_authority="NONE_RESEARCH_ONLY",
        family_activation_authority="NONE_PROGRAMME_BUDGET_UNFROZEN",
    )
