"""ThetaData end-of-day option chains: one request per symbol per session.

Used by the backtest (the decision chain of each past session) and by the
risk-premium history (the 30-day implied vol at each past close). The EOD
report carries the last NBBO of the session, so quotes are stamped 16:00 New
York.
"""
from __future__ import annotations

import time as clock
from datetime import UTC, date, datetime, time
from typing import Any, Iterable

from src.engine.chains import NY, Quote
from src.engine.history import RETRY_ATTEMPTS, RETRYABLE_MARKERS


def flatten_eod_payload(payload: Any) -> list[dict]:
    rows = payload.get("response") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise ValueError("ThetaData option EOD payload is not a list")
    flat: list[dict] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        contract, data = item.get("contract"), item.get("data")
        if isinstance(contract, dict) and isinstance(data, list):
            for obs in data:
                if isinstance(obs, dict):
                    flat.append({**contract, **obs})
        else:
            flat.append(dict(item))
    return flat


def _right(value: Any) -> str | None:
    text = str(value or "").strip().upper()
    return "C" if text in {"C", "CALL"} else "P" if text in {"P", "PUT"} else None


def quotes_from_eod_rows(rows: Iterable[dict], session: date) -> list[Quote]:
    stamp = datetime.combine(session, time(16, 0), NY).astimezone(UTC).isoformat().replace("+00:00", "Z")
    out: list[Quote] = []
    for r in rows:
        right = _right(r.get("right"))
        try:
            strike = float(r["strike"])
            expiration = str(r["expiration"])[:10]
            if len(expiration) == 8 and expiration.isdigit():
                expiration = f"{expiration[:4]}-{expiration[4:6]}-{expiration[6:]}"
            bid = None if r.get("bid") in (None, "") else float(r["bid"])
            ask = None if r.get("ask") in (None, "") else float(r["ask"])
        except (KeyError, TypeError, ValueError):
            continue
        if right is None or strike <= 0:
            continue
        out.append(Quote(right, strike, expiration, bid, ask, stamp, None))
    return out


def fetch_eod_chain_rows(theta_client, symbol: str, session: date, *, max_dte: int = 45) -> list[dict]:
    """All contracts expiring within ``max_dte`` days with their EOD quote, flattened.
    Retries rate limiting and transient gateway errors with backoff; anything else
    propagates (a dead terminal must be seen by the caller)."""
    from src.providers.thetadata import ThetaDataResponseError, ThetaDataUnavailable

    delay = 2.0
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            payload = theta_client._get_payload(
                "/option/history/eod",
                {"symbol": symbol.upper(), "expiration": "*",
                 "start_date": session.strftime("%Y%m%d"),
                 "end_date": session.strftime("%Y%m%d"), "max_dte": max_dte},
            )
            return flatten_eod_payload(payload)
        except (ThetaDataResponseError, ThetaDataUnavailable) as exc:
            text = str(exc).lower()
            if attempt == RETRY_ATTEMPTS or not any(m in text for m in RETRYABLE_MARKERS):
                raise
            clock.sleep(delay)
            delay = min(delay * 2, 20.0)
    raise RuntimeError("unreachable")


def session_close(session: date) -> datetime:
    return datetime.combine(session, time(16, 0), NY).astimezone(UTC)
