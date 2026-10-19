"""Conservative as-of observation of a real stock price already in Massive data.

The Massive *options-chain snapshot* includes the underlying_asset.price and
last_updated (Unix nanoseconds) when licensed. This is a stock last/reference
observation from a SEPARATE provider, not Theta's model_underlying_price,
an exchange auction price, or the option's OCC settlement. Never recompute
historical entry spots from future EOD or from inferred option Greeks.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence

VERSION = "MASSIVE_FROZEN_UNDERLYING_OBSERVATION_V1"
STOCK_PRICE_SOURCE = "MASSIVE_OPTION_CHAIN_UNDERLYING_ASSET_LAST"
MAX_AGE_SECONDS = 15  # existing Stage-0 quote-freshness window; stale cross-vendor spots are unsafe


@dataclass(frozen=True)
class IndependentUnderlyingObservation:
    price: float
    observed_at: str
    source: str = STOCK_PRICE_SOURCE
    measurement_role: str = "ASOF_STOCK_PRICE_REFERENCE_NOT_SETTLEMENT"
    version: str = VERSION


def extract_massive_underlying_observation(
    snapshot_rows: Sequence[dict[str, Any]],
    *,
    underlying: str,
    decision_at: datetime,
) -> IndependentUnderlyingObservation | None:
    """Select timestamped, coherent source data no later than the Theta cut.

    Only an underlying_asset that explicitly identifies the requested ticker
    is usable. Missing identity/time, negative/future/stale quotes or a
    contradictory same-time observation do not get guessed or backfilled.
    """
    if decision_at.tzinfo is None or decision_at.utcoffset() is None:
        raise ValueError("THETA_DECISION_TIME_MUST_BE_TIMEZONE_AWARE")
    symbol = str(underlying).strip().upper()
    cut = decision_at.astimezone(timezone.utc)
    if not symbol:
        raise ValueError("UNDERLYING_SYMBOL_REQUIRED")
    candidates: list[tuple[datetime, float]] = []
    for row in snapshot_rows:
        asset = row.get("underlying_asset") if isinstance(row, dict) else None
        if not isinstance(asset, dict):
            continue
        if str(asset.get("ticker", "")).strip().upper() != symbol:
            continue
        raw = asset.get("last_updated")
        px = asset.get("price")
        if isinstance(raw, bool) or not isinstance(raw, int) or raw <= 0:
            continue
        if isinstance(px, bool) or not isinstance(px, (float, int)):
            continue
        px = float(px)
        if not math.isfinite(px) or px <= 0.0:
            continue
        try:
            observed = datetime.fromtimestamp(raw / 1_000_000_000, tz=timezone.utc)
        except (ValueError, OSError, OverflowError):
            continue
        age = (cut - observed).total_seconds()
        if 0 <= age <= MAX_AGE_SECONDS:
            candidates.append((observed, px))
    if not candidates:
        return None
    latest_time = max(t for t, _ in candidates)
    at_latest = {p for t, p in candidates if t == latest_time}
    if len(at_latest) != 1:
        return None
    return IndependentUnderlyingObservation(
        price=at_latest.pop(), observed_at=latest_time.isoformat(
            timespec="microseconds"
        ).replace("+00:00", "Z"),
    )
