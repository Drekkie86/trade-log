"""Daily close history for the models, and settlement prices for outcomes.

Primary source: ThetaData stock EOD reports, stored in engine_daily_closes.
Gap filler for the models only: the last snapshot underlying price per
session (never persisted as a close). Settlement uses the ThetaData EOD close
or, failing that, a snapshot price captured within 15 minutes of the close.
"""
from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Iterable, Sequence

from src.engine.chains import NY, parse_utc

HISTORY_DAYS = 760          # ~3 years of calendar days, ~500 sessions
EOD_AVAILABLE_AFTER = time(17, 30)


@dataclass(frozen=True)
class DailyClose:
    session_date: str
    close: float


def parse_eod_rows(payload: Any) -> list[DailyClose]:
    rows = payload.get("response") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise ValueError("ThetaData EOD payload is not a list")
    out: dict[str, float] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        raw_close = row.get("close")
        created = row.get("created") or row.get("last_trade")
        if isinstance(raw_close, bool) or created is None:
            continue
        try:
            close = float(raw_close)
            stamp = datetime.fromisoformat(str(created).strip())
        except (TypeError, ValueError):
            continue
        if not math.isfinite(close) or close <= 0:
            continue
        out[stamp.date().isoformat()] = close
    return [DailyClose(d, out[d]) for d in sorted(out)]


def fetch_eod_closes(theta_client, symbol: str, start: date, end: date) -> list[DailyClose]:
    payload = theta_client._get_payload(
        "/stock/history/eod",
        {"symbol": symbol.upper(), "start_date": start.strftime("%Y%m%d"),
         "end_date": end.strftime("%Y%m%d")},
    )
    return parse_eod_rows(payload)


def last_completed_session(now: datetime, calendar=None) -> date | None:
    """Most recent session whose EOD report should exist at ``now``."""
    from src.operations.market_calendar import get_xnys_calendar

    cal = calendar or get_xnys_calendar()
    local = now.astimezone(NY)
    day = local.date()
    if not (cal.is_session(day.isoformat()) and local.time() >= EOD_AVAILABLE_AFTER):
        day = day - timedelta(days=1)
    for _ in range(10):
        if cal.is_session(day.isoformat()):
            return day
        day -= timedelta(days=1)
    return None


def latest_stored(conn: sqlite3.Connection, symbol: str) -> str | None:
    row = conn.execute(
        "SELECT MAX(session_date) FROM engine_daily_closes WHERE symbol=?", (symbol,)
    ).fetchone()
    return row[0] if row else None


def refresh_closes(conn: sqlite3.Connection, theta_client, symbols: Iterable[str], *,
                   now: datetime, max_symbols: int = 16, calendar=None) -> dict[str, str]:
    """Bring stale symbols up to the last completed session. Returns status per symbol."""
    target = last_completed_session(now, calendar)
    status: dict[str, str] = {}
    if target is None:
        return status
    fetched_at = now.astimezone(UTC).isoformat().replace("+00:00", "Z")
    budget = max_symbols
    for symbol in sorted({s.upper() for s in symbols}):
        latest = latest_stored(conn, symbol)
        if latest is not None and latest >= target.isoformat():
            status[symbol] = "CURRENT"
            continue
        if budget <= 0:
            status[symbol] = "DEFERRED"
            continue
        budget -= 1
        start = (date.fromisoformat(latest) + timedelta(days=1)) if latest \
            else target - timedelta(days=HISTORY_DAYS)
        try:
            closes = fetch_eod_closes(theta_client, symbol, start, target)
        except Exception as exc:  # provider failure must not stop the engine
            status[symbol] = f"FAILED:{type(exc).__name__}"
            continue
        with conn:
            conn.executemany(
                """INSERT OR IGNORE INTO engine_daily_closes
                   (symbol, session_date, close, source, fetched_at)
                   VALUES (?, ?, ?, 'THETADATA_EOD', ?)""",
                [(symbol, c.session_date, c.close, fetched_at) for c in closes
                 if c.session_date <= target.isoformat()],
            )
        status[symbol] = f"FETCHED:{len(closes)}"
    return status


def _snapshot_daily_last(conn: sqlite3.Connection, symbol: str) -> dict[str, float]:
    rows = conn.execute(
        """SELECT us_session_date, underlying_price FROM market_snapshots
           WHERE underlying=? AND underlying_price IS NOT NULL
             AND us_session_date IS NOT NULL AND us_session_state='INTRADAY'
           ORDER BY id""",
        (symbol,),
    ).fetchall()
    out: dict[str, float] = {}
    for r in rows:
        out[str(r[0])] = float(r[1])
    return out


def load_closes(conn: sqlite3.Connection, symbol: str, *, before: date) -> list[float]:
    """Ascending closes strictly before ``before`` (today's session excluded)."""
    symbol = symbol.upper()
    stored = {
        str(r[0]): float(r[1]) for r in conn.execute(
            "SELECT session_date, close FROM engine_daily_closes WHERE symbol=? AND session_date<?",
            (symbol, before.isoformat()),
        )
    }
    for d, px in _snapshot_daily_last(conn, symbol).items():
        if d < before.isoformat():
            stored.setdefault(d, px)
    return [stored[d] for d in sorted(stored)]


def settlement_price(conn: sqlite3.Connection, symbol: str,
                     session_date: str) -> tuple[float, str] | None:
    row = conn.execute(
        "SELECT close FROM engine_daily_closes WHERE symbol=? AND session_date=?",
        (symbol.upper(), session_date),
    ).fetchone()
    if row is not None:
        return float(row[0]), "THETADATA_EOD"
    close_at = datetime.combine(date.fromisoformat(session_date), time(16, 0), NY)
    lo = (close_at - timedelta(minutes=15)).astimezone(UTC)
    hi = (close_at + timedelta(minutes=5)).astimezone(UTC)
    best = None
    for r in conn.execute(
        """SELECT captured_at, underlying_price FROM market_snapshots
           WHERE underlying=? AND us_session_date=? AND underlying_price IS NOT NULL""",
        (symbol.upper(), session_date),
    ):
        stamp = parse_utc(r[0])
        if stamp is not None and lo <= stamp <= hi:
            if best is None or stamp > best[0]:
                best = (stamp, float(r[1]))
    return (best[1], "SNAPSHOT_NEAR_CLOSE") if best else None
