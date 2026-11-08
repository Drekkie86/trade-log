from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from pathlib import Path
from typing import Any

import numpy as np

from src.database.repository import resolve_db_path
from src.operations.sqlite_runtime import open_readonly_connection
from src.quant.forecast_validation import tournament
from src.quant.rolling_variance_forecast import RollingForecastConfig, rolling_variance_forecasts
from src.research.surface_intelligence_v1 import SurfacePoint, compare_surface_models


RUNTIME_VERSION = "1.0.0"


@dataclass(frozen=True)
class UnderlyingForecastRuntime:
    underlying: str
    session_price_count: int
    return_count: int
    state: str
    detail: str
    tournament: dict[str, Any] | None


@dataclass(frozen=True)
class SurfaceRuntime:
    research_run_id: int | None
    underlying: str | None
    expiration: str | None
    right: str | None
    point_count: int
    state: str
    detail: str
    tournament: dict[str, Any] | None


@dataclass(frozen=True)
class ForecastSurfaceRuntime:
    version: str
    state: str
    underlying_forecasts: tuple[UnderlyingForecastRuntime, ...]
    surface: SurfaceRuntime
    decision_authority: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "state": self.state,
            "underlying_forecasts": [asdict(item) for item in self.underlying_forecasts],
            "surface": asdict(self.surface),
            "decision_authority": self.decision_authority,
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
        SELECT r.underlying, r.us_session_date, r.underlying_price
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


def _log_returns(prices: list[float]) -> list[float]:
    if len(prices) < 2:
        return []
    array = np.asarray(prices, dtype=float)
    if np.any(~np.isfinite(array)) or np.any(array <= 0):
        return []
    return list(np.diff(np.log(array)).astype(float))


def _latest_surface(conn) -> tuple[int | None, str | None, str | None, str | None, list[SurfacePoint]]:
    key = conn.execute(
        """
        SELECT
            ms.research_run_id,
            ms.underlying,
            oq.expiration,
            oq.right,
            COUNT(*) AS point_count
        FROM option_quotes AS oq
        JOIN market_snapshots AS ms ON ms.id = oq.snapshot_id
        JOIN provider_model_observations AS pmo
          ON pmo.option_quote_id = oq.id
         AND pmo.provider = 'THETADATA'
        WHERE ms.research_run_id IS NOT NULL
          AND pmo.implied_volatility IS NOT NULL
          AND pmo.implied_volatility > 0
        GROUP BY ms.research_run_id, ms.underlying, oq.expiration, oq.right
        HAVING COUNT(*) >= 5
        ORDER BY ms.research_run_id DESC, point_count DESC, ms.underlying, oq.expiration, oq.right
        LIMIT 1;
        """
    ).fetchone()
    if key is None:
        return None, None, None, None, []
    rows = conn.execute(
        """
        SELECT oq.strike, AVG(pmo.implied_volatility) AS implied_volatility
        FROM option_quotes AS oq
        JOIN market_snapshots AS ms ON ms.id = oq.snapshot_id
        JOIN provider_model_observations AS pmo
          ON pmo.option_quote_id = oq.id
         AND pmo.provider = 'THETADATA'
        WHERE ms.research_run_id = ?
          AND ms.underlying = ?
          AND oq.expiration = ?
          AND oq.right = ?
          AND pmo.implied_volatility IS NOT NULL
          AND pmo.implied_volatility > 0
        GROUP BY oq.strike
        ORDER BY oq.strike;
        """,
        (
            int(key["research_run_id"]),
            str(key["underlying"]),
            str(key["expiration"]),
            str(key["right"]),
        ),
    ).fetchall()
    points = [SurfacePoint(float(row["strike"]), float(row["implied_volatility"])) for row in rows]
    return (
        int(key["research_run_id"]),
        str(key["underlying"]),
        str(key["expiration"]),
        str(key["right"]),
        points,
    )


def load_forecast_surface_runtime(
    db_path: str | Path | None = None,
    *,
    train_window: int = 40,
    horizon_days: int = 5,
    limit_underlyings: int = 8,
    bootstrap_samples: int = 500,
) -> ForecastSurfaceRuntime:
    path = resolve_db_path(db_path)
    if not path.exists():
        return ForecastSurfaceRuntime(
            version=RUNTIME_VERSION,
            state="DATABASE_UNAVAILABLE",
            underlying_forecasts=(),
            surface=SurfaceRuntime(None, None, None, None, 0, "NO_DATA", "Database is unavailable.", None),
            decision_authority="NONE_RESEARCH_ONLY",
        )

    conn = open_readonly_connection(path)
    try:
        price_map = _session_prices(conn, limit_underlyings=limit_underlyings)
        surface_key = _latest_surface(conn)
    finally:
        conn.close()

    forecast_states: list[UnderlyingForecastRuntime] = []
    config = RollingForecastConfig(train_window=train_window, horizon_days=horizon_days, include_garch=True)
    required_returns = train_window + horizon_days
    for underlying, prices in price_map.items():
        returns = _log_returns(prices)
        if len(returns) < required_returns:
            forecast_states.append(
                UnderlyingForecastRuntime(
                    underlying=underlying,
                    session_price_count=len(prices),
                    return_count=len(returns),
                    state="ACCUMULATING_HISTORY",
                    detail=f"Need at least {required_returns} daily returns; have {len(returns)}.",
                    tournament=None,
                )
            )
            continue
        rows = rolling_variance_forecasts(returns, config=config)
        result = tournament(rows, scoring_rule="QLIKE", bootstrap_samples=bootstrap_samples)
        forecast_states.append(
            UnderlyingForecastRuntime(
                underlying=underlying,
                session_price_count=len(prices),
                return_count=len(returns),
                state="FORECAST_TOURNAMENT_AVAILABLE",
                detail="Rolling-origin historical variance, EWMA and GARCH(1,1) forecasts are comparable.",
                tournament=result.as_dict(),
            )
        )

    research_run_id, underlying, expiration, right, points = surface_key
    if len(points) < 5:
        surface = SurfaceRuntime(
            research_run_id,
            underlying,
            expiration,
            right,
            len(points),
            "ACCUMULATING_SURFACE",
            "No current surface slice with at least five valid Theta IV strikes is available.",
            None,
        )
    else:
        surface_result = compare_surface_models(points)
        surface = SurfaceRuntime(
            research_run_id,
            underlying,
            expiration,
            right,
            len(points),
            "SURFACE_TOURNAMENT_AVAILABLE",
            "Frozen local-quadratic incumbent and nearest-bracket linear challenger are compared observationally.",
            surface_result.as_dict(),
        )

    any_forecast = any(item.state == "FORECAST_TOURNAMENT_AVAILABLE" for item in forecast_states)
    if any_forecast and surface.state == "SURFACE_TOURNAMENT_AVAILABLE":
        state = "RESEARCH_COMPARISONS_AVAILABLE"
    elif forecast_states or surface.point_count:
        state = "ACCUMULATING_EVIDENCE"
    else:
        state = "NO_RESEARCH_DATA"

    return ForecastSurfaceRuntime(
        version=RUNTIME_VERSION,
        state=state,
        underlying_forecasts=tuple(forecast_states),
        surface=surface,
        decision_authority="NONE_RESEARCH_ONLY",
    )
