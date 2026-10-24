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
DIRECT_STOCK_PRICE_SOURCE = "MASSIVE_STOCK_SNAPSHOT_LAST_TRADE"
STOCK_PRICE_SOURCES = frozenset({
    STOCK_PRICE_SOURCE, DIRECT_STOCK_PRICE_SOURCE,
})
MAX_AGE_SECONDS = 15  # existing Stage-0 quote-freshness window; stale cross-vendor spots are unsafe


def verified_stock_source_from_notes(notes: str | None) -> str | None:
    """Exactly one trusted direct stock-tape source, never Greek-model spot."""
    text = str(notes or "")
    found = [
        source for source in STOCK_PRICE_SOURCES
        if f"stock price source={source};" in text
    ]
    return found[0] if len(found) == 1 else None


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


@dataclass(frozen=True)
class StockSourceDisposition:
    """Machine-readable source failure, not an alternative spot estimate."""
    status: str
    reason: str
    chain_rows: int
    matched_ticker_rows: int
    structurally_valid_rows: int
    qualifying_rows: int
    closest_age_seconds: float | None = None


def diagnose_stock_source(
    snapshot_rows: Sequence[dict[str, Any]],
    *,
    underlying: str,
    decision_at: datetime,
) -> StockSourceDisposition:
    """Explain why independent spot evidence did or did not qualify.

    No guessing a ticker, coercing a unitless timestamp, or replaying the
    Greek-model underlying. The actual extraction function is authoritative.
    Diagnostics are bounded to the already-retrieved provider rows.
    """
    if decision_at.tzinfo is None or decision_at.utcoffset() is None:
        raise ValueError("THETA_DECISION_TIME_MUST_BE_TIMEZONE_AWARE")
    symbol = str(underlying).strip().upper()
    if not symbol:
        raise ValueError("UNDERLYING_SYMBOL_REQUIRED")
    cut = decision_at.astimezone(timezone.utc)
    stats = {
        "NO_UNDERLYING_ASSET": 0,
        "TICKER_MISSING": 0,
        "TICKER_MISMATCH": 0,
        "PRICE_INVALID": 0,
        "TIMESTAMP_INVALID": 0,
        "SOURCE_FROM_FUTURE": 0,
        "SOURCE_STALE_AT_THETA_CUT": 0,
        "CANDIDATE_FRESH": 0,
    }
    matched = valid = fresh = 0
    ages: list[float] = []
    timestamps: dict[int, set[float]] = {}
    for row in snapshot_rows:
        asset = row.get("underlying_asset") if isinstance(row, dict) else None
        if not isinstance(asset, dict):
            stats["NO_UNDERLYING_ASSET"] += 1
            continue
        raw_ticker = str(asset.get("ticker") or "").strip().upper()
        if not raw_ticker:
            stats["TICKER_MISSING"] += 1
            continue
        if raw_ticker != symbol:
            stats["TICKER_MISMATCH"] += 1
            continue
        matched += 1
        px = asset.get("price")
        if isinstance(px, bool) or not isinstance(px, (int, float)):
            stats["PRICE_INVALID"] += 1
            continue
        price = float(px)
        if not math.isfinite(price) or price <= 0:
            stats["PRICE_INVALID"] += 1
            continue
        nanoseconds = asset.get("last_updated")
        if (
            isinstance(nanoseconds, bool)
            or not isinstance(nanoseconds, int) or nanoseconds <= 0
        ):
            stats["TIMESTAMP_INVALID"] += 1
            continue
        try:
            t = datetime.fromtimestamp(nanoseconds / 1e9, tz=timezone.utc)
        except (ValueError, OSError, OverflowError):
            stats["TIMESTAMP_INVALID"] += 1
            continue
        valid += 1
        age = (cut - t).total_seconds()
        ages.append(age)
        if age < 0:
            stats["SOURCE_FROM_FUTURE"] += 1
        elif age > MAX_AGE_SECONDS:
            stats["SOURCE_STALE_AT_THETA_CUT"] += 1
        else:
            fresh += 1
            stats["CANDIDATE_FRESH"] += 1
            timestamps.setdefault(nanoseconds, set()).add(price)

    ambiguous = bool(timestamps) and len(
        timestamps[max(timestamps)]
    ) > 1
    if fresh and not ambiguous:
        status, reason = "QUALIFIED", "QUALIFIED_INDEPENDENT_STOCK_REFERENCE"
    elif ambiguous:
        status, reason = "BLOCKED", "CONTRADICTORY_SAME_TIMESTAMP"
    else:
        reason = next(
            (
                key for key in (
                    "SOURCE_STALE_AT_THETA_CUT", "SOURCE_FROM_FUTURE",
                    "TIMESTAMP_INVALID", "PRICE_INVALID", "TICKER_MISSING",
                    "TICKER_MISMATCH", "NO_UNDERLYING_ASSET",
                ) if stats[key]
            ),
            "NO_CHAIN_ROWS",
        )
        status = "BLOCKED"
    return StockSourceDisposition(
        status=status, reason=reason,
        chain_rows=len(snapshot_rows),
        matched_ticker_rows=matched,
        structurally_valid_rows=valid,
        qualifying_rows=fresh,
        closest_age_seconds=(
            round(min(ages, key=abs), 3) if ages else None
        ),
    )
