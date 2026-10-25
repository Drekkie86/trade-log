"""Timestamped Massive STOCKS snapshot last-trade source, never model spot.

Separate from the options-chain asset field; may require Stocks entitlement.
No last-trade, delayed-only plan, wrong ticker, future or stale timestamp
can be promoted into trade evidence. This source is explicitly opt-in.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime,timezone
from typing import Any

from src.research.massive_underlying_observation_v1 import (
    IndependentUnderlyingObservation, MAX_AGE_SECONDS,
)

VERSION = "MASSIVE_STOCKS_LAST_TRADE_SOURCE_V1"
SOURCE = "MASSIVE_STOCK_SNAPSHOT_LAST_TRADE"


@dataclass(frozen=True)
class DirectStockResult:
    observation: IndependentUnderlyingObservation | None
    reason: str
    request_made: bool = False


def parse_stock_ticker_snapshot(
    payload: Any,
    *,
    underlying: str,
    decision_at: datetime,
) -> DirectStockResult:
    if decision_at.tzinfo is None or decision_at.utcoffset() is None:
        raise ValueError("THETA_DECISION_TIME_MUST_BE_TIMEZONE_AWARE")
    symbol = str(underlying).strip().upper()
    if not symbol or len(symbol)>16 or not symbol.replace(".","").isalnum():
        raise ValueError("INVALID_STOCK_TICKER")
    if not isinstance(payload,dict):
        return DirectStockResult(None,"STOCK_RESPONSE_NOT_OBJECT",True)
    if payload.get("status") in {"NOT_ENTITLED","FORBIDDEN"}:
        return DirectStockResult(None,"STOCK_TRADE_NOT_ENTITLED",True)
    ticker = payload.get("ticker")
    if not isinstance(ticker,dict):
        return DirectStockResult(None,"STOCK_TICKER_PAYLOAD_MISSING",True)
    if str(ticker.get("ticker") or "").upper()!=symbol:
        return DirectStockResult(None,"STOCK_TICKER_IDENTITY_MISMATCH",True)
    trade=ticker.get("lastTrade")
    if not isinstance(trade,dict):
        return DirectStockResult(None,"STOCK_LAST_TRADE_NOT_IN_PLAN_OR_RESPONSE",True)
    price=trade.get("p")
    timestamp=trade.get("t")
    if (isinstance(price,bool) or not isinstance(price,(float,int))
        or not math.isfinite(price) or price<=0):
        return DirectStockResult(None,"STOCK_LAST_TRADE_PRICE_INVALID",True)
    if isinstance(timestamp,bool) or not isinstance(timestamp,int) or timestamp<=0:
        return DirectStockResult(None,"STOCK_LAST_TRADE_TIME_INVALID",True)
    try:
        at=datetime.fromtimestamp(timestamp/1_000_000_000,tz=timezone.utc)
    except (OverflowError,ValueError,OSError):
        return DirectStockResult(None,"STOCK_LAST_TRADE_TIME_INVALID",True)
    age=(decision_at.astimezone(timezone.utc)-at).total_seconds()
    if age<0:
        return DirectStockResult(None,"STOCK_TRADE_AFTER_OPTION_CUT",True)
    if age>MAX_AGE_SECONDS:
        return DirectStockResult(None,"STOCK_TRADE_STALE_AT_OPTION_CUT",True)
    return DirectStockResult(
        IndependentUnderlyingObservation(
            price=float(price),
            observed_at=at.isoformat(timespec="microseconds").replace("+00:00","Z"),
            source=SOURCE,
            version=VERSION,
        ),
        "QUALIFIED_STOCK_LAST_TRADE",True,
    )
