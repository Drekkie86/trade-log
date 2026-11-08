"""Strict read-only interpretation of ThetaData v3 *stock EOD* references.

These reports are generated around 17:15 New York time and can contain an
after-hours last trade. This is NOT a 16:00 closing auction, OCC settlement,
option execution, or validated payoff source.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from src.providers.thetadata import ThetaDataClient

NY = ZoneInfo("America/New_York")
MEASUREMENT_ROLE = "THETADATA_STOCK_EOD_POSTSESSION_REFERENCE_NOT_SETTLEMENT"
PARSER_VERSION = "STOCK_EOD_REFERENCE_V1"


class StockEodReferenceError(ValueError):
    """Missing, stale, incoherent or unsupported provider report."""


@dataclass(frozen=True)
class StockEodReference:
    symbol: str
    session_date: str
    reported_close: float
    report_generated_at: str
    last_trade_at: str
    fetched_at: str
    row_sha256: str
    last_trade_after_1600_ny: bool
    source: str = "THETADATA_V3_STOCK_HISTORY_EOD"
    measurement_role: str = MEASUREMENT_ROLE
    parser_version: str = PARSER_VERSION


def _local_timestamp(raw: object, field: str, day: date) -> datetime:
    if not isinstance(raw, str):
        raise StockEodReferenceError(f"{field}: MISSING_PROVIDER_TIMESTAMP")
    try:
        stamp = datetime.fromisoformat(raw.strip())
    except ValueError as exc:
        raise StockEodReferenceError(f"{field}: INVALID_PROVIDER_TIMESTAMP") from exc
    # ThetaData v3 documents naive US/Eastern timestamps. Do not silently
    # treat them as UTC or mix different timestamp semantics.
    if stamp.tzinfo is not None or stamp.date() != day:
        raise StockEodReferenceError(f"{field}: WRONG_TIMEZONE_OR_SESSION")
    return stamp.replace(tzinfo=NY)


def parse_stock_eod_reference(
    payload: Any, *, symbol: str, session_date: date,
    fetched_at: datetime | None = None,
) -> StockEodReference:
    if isinstance(payload, dict):
        rows = payload.get("response")
    else:
        rows = payload
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        raise StockEodReferenceError("NO_UNAMBIGUOUS_EOD_REPORT")
    row = rows[0]
    symbol = str(symbol).upper().strip()
    if not symbol or len(symbol) > 16 or not symbol.replace(".", "").isalnum():
        raise StockEodReferenceError("INVALID_SYMBOL")
    value = row.get("close")
    if isinstance(value, bool):
        raise StockEodReferenceError("INVALID_EOD_CLOSE")
    try:
        close = float(value)
    except (ValueError, TypeError, OverflowError) as exc:
        raise StockEodReferenceError("INVALID_EOD_CLOSE") from exc
    if not math.isfinite(close) or close <= 0.0:
        raise StockEodReferenceError("INVALID_EOD_CLOSE")
    created = _local_timestamp(row.get("created"), "created", session_date)
    traded = _local_timestamp(row.get("last_trade"), "last_trade", session_date)
    if traded > created or created.time() < time(16, 0):
        raise StockEodReferenceError("INCOHERENT_EOD_REPORT_CLOCK")
    now = fetched_at or datetime.now(UTC)
    if now.tzinfo is None or now.utcoffset() is None:
        raise StockEodReferenceError("FETCH_TIMEZONE_UNKNOWN")
    # Never claim evidence was obtained before the vendor report was made.
    if created.astimezone(UTC) > now.astimezone(UTC):
        raise StockEodReferenceError("REPORT_FROM_FUTURE")
    digest = hashlib.sha256(
        json.dumps(row, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()
    return StockEodReference(
        symbol=symbol, session_date=session_date.isoformat(),
        reported_close=close,
        report_generated_at=created.isoformat(),
        last_trade_at=traded.isoformat(),
        fetched_at=now.astimezone(UTC).isoformat(),
        row_sha256=digest,
        last_trade_after_1600_ny=traded.time() >= time(16, 0),
    )


def fetch_stock_eod_reference(
    symbol: str, session_date: date, *,
    client: ThetaDataClient | None = None,
    fetched_at: datetime | None = None,
) -> StockEodReference:
    """One bounded vendor request; no DB writes or fallback to model Greeks."""
    theta = client or ThetaDataClient(timeout_seconds=12.0)
    day = session_date.strftime("%Y%m%d")
    payload = theta._get_payload(
        "/stock/history/eod",
        {"symbol": str(symbol).upper(), "start_date": day, "end_date": day},
    )
    return parse_stock_eod_reference(
        payload, symbol=symbol, session_date=session_date,
        fetched_at=fetched_at,
    )
