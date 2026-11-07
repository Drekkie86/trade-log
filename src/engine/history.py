"""Daily close history for the models, and settlement prices for outcomes.

Single source: ThetaData stock EOD reports (``/v3/stock/history/eod``, every
tier), stored in ``engine_daily_closes`` with the report's last-trade time so
an after-hours print is visible. Requests are chunked to the provider's
365-day cap. Nothing is gap-filled from intraday snapshots: a missing session
stays missing and shows up in ``history_status``.
"""
from __future__ import annotations

import math
import os
import sqlite3
import time as _time
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Iterable

from src.engine.chains import NY

HISTORY_DAYS = 760              # ~3 years of calendar days, ~500 sessions
MAX_REQUEST_DAYS = 360          # ThetaData caps one EOD request at 365 days
EOD_AVAILABLE_AFTER = time(17, 30)
OFFICIAL_CLOSE = time(16, 0, 5)


@dataclass(frozen=True)
class DailyClose:
    """One EOD report row. ``after_hours`` records that the report's last trade printed
    after 16:00 New York; for liquid names that is nearly always true and the ``close``
    field still matched neither the 17:15 bid nor ask in the 2026-11-07 probe, so it is
    kept for audit, not raised as a warning."""
    session_date: str
    close: float
    last_trade_at: str | None = None
    after_hours: bool = False


def parse_eod_rows(payload: Any) -> list[DailyClose]:
    rows = payload.get("response") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise ValueError("ThetaData EOD payload is not a list")
    out: dict[str, DailyClose] = {}
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
        last_trade = row.get("last_trade")
        last_trade_at, after_hours = None, False
        if last_trade:
            try:
                lt = datetime.fromisoformat(str(last_trade).strip())
                last_trade_at = lt.isoformat(timespec="seconds")
                after_hours = lt.time() > OFFICIAL_CLOSE
            except ValueError:
                pass
        day = stamp.date().isoformat()
        out[day] = DailyClose(day, close, last_trade_at, after_hours)
    return [out[d] for d in sorted(out)]


def stock_history_first_date() -> date:
    """Earliest session the stock subscription serves (FREE tier: 2023-06-01).

    Requests that start before it are rejected by the terminal, so the window is
    clamped. Override with CHRISTIANIA_STOCK_HISTORY_FIRST_DATE after an upgrade.
    """
    raw = os.environ.get("CHRISTIANIA_STOCK_HISTORY_FIRST_DATE", "2023-06-01")
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return date(2023, 6, 1)


RETRYABLE_MARKERS = ("429", "rate limit", "too many requests", "502", "503", "504")
RETRY_ATTEMPTS = 5


def _eod_request(theta_client, symbol: str, chunk_start: date, chunk_end: date) -> Any:
    """One EOD request with backoff on rate limiting and transient errors."""
    from src.providers.thetadata import ThetaDataResponseError, ThetaDataUnavailable

    delay = 2.0
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            return theta_client._get_payload(
                "/stock/history/eod",
                {"symbol": symbol.upper(), "start_date": chunk_start.strftime("%Y%m%d"),
                 "end_date": chunk_end.strftime("%Y%m%d")},
            )
        except (ThetaDataResponseError, ThetaDataUnavailable) as exc:
            text = str(exc).lower()
            if attempt == RETRY_ATTEMPTS or not any(m in text for m in RETRYABLE_MARKERS):
                raise
            _time.sleep(delay)
            delay = min(delay * 2, 20.0)


def fetch_eod_closes(theta_client, symbol: str, start: date, end: date, *,
                     pace_seconds: float = 0.0, today: date | None = None,
                     problems: list[str] | None = None) -> list[DailyClose]:
    """Bounded requests (<= MAX_REQUEST_DAYS each) from max(start, first served date)
    to min(end, today).

    A chunk that the terminal rejects is skipped and the others are kept (the
    message goes to ``problems``); the error is raised only when every chunk
    failed. ``pace_seconds`` sleeps between requests to stay under the stock
    tier's per-minute limit.
    """
    from src.providers.thetadata import ThetaDataError

    out: list[DailyClose] = []
    today = today or datetime.now(UTC).astimezone(NY).date()
    end = min(end, today)
    chunk_start = max(start, stock_history_first_date())
    if chunk_start > end:
        return out
    failures: list[Exception] = []
    attempted = 0
    while chunk_start <= end:
        chunk_end = min(end, chunk_start + timedelta(days=MAX_REQUEST_DAYS - 1))
        attempted += 1
        try:
            out.extend(parse_eod_rows(_eod_request(theta_client, symbol, chunk_start, chunk_end)))
        except ThetaDataError as exc:
            failures.append(exc)
            if problems is not None:
                problems.append(f"{symbol} {chunk_start}..{chunk_end}: {str(exc)[:160]}")
        chunk_start = chunk_end + timedelta(days=1)
        if pace_seconds and chunk_start <= end:
            _time.sleep(pace_seconds)
    if failures and len(failures) == attempted:
        raise failures[-1]
    return out


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
                   (symbol, session_date, close, source, fetched_at, last_trade_at, after_hours)
                   VALUES (?, ?, ?, 'THETADATA_EOD', ?, ?, ?)""",
                [(symbol, c.session_date, c.close, fetched_at, c.last_trade_at, int(c.after_hours))
                 for c in closes if c.session_date <= target.isoformat()],
            )
        status[symbol] = f"FETCHED:{len(closes)}"
    return status


def load_closes(conn: sqlite3.Connection, symbol: str, *, before: date) -> list[float]:
    """Ascending EOD closes strictly before ``before`` (today's session excluded)."""
    return [
        float(r[0]) for r in conn.execute(
            """SELECT close FROM engine_daily_closes WHERE symbol=? AND session_date<?
               ORDER BY session_date""",
            (symbol.upper(), before.isoformat()),
        )
    ]


@dataclass(frozen=True)
class HistoryStatus:
    symbols: int
    current: int
    stale: int
    missing: int
    oldest_gap_days: int | None
    target: str | None

    @property
    def ok(self) -> bool | None:
        if self.symbols == 0:
            return None
        return self.current == self.symbols

    def sentence(self) -> str:
        if self.symbols == 0:
            return "No symbols to check yet."
        text = f"Closes current for {self.current} of {self.symbols} symbols"
        if self.missing:
            text += f"; {self.missing} with no history at all"
        if self.stale and self.oldest_gap_days:
            text += f"; oldest gap {self.oldest_gap_days} sessions"
        return text + (f" (target {self.target})." if self.target else ".")


def history_status(conn: sqlite3.Connection, symbols: Iterable[str], *, now: datetime,
                   calendar=None) -> HistoryStatus:
    from src.operations.market_calendar import get_xnys_calendar

    cal = calendar or get_xnys_calendar()
    target = last_completed_session(now, calendar)
    syms = sorted({s.upper() for s in symbols})
    current = stale = missing = 0
    oldest_gap = None
    for s in syms:
        latest = latest_stored(conn, s)
        if latest is None:
            missing += 1
            continue
        if target is None or latest >= target.isoformat():
            current += 1
            continue
        stale += 1
        gap = len(cal.sessions_in_range((date.fromisoformat(latest) + timedelta(days=1)).isoformat(),
                                        target.isoformat()))
        oldest_gap = gap if oldest_gap is None else max(oldest_gap, gap)
    return HistoryStatus(len(syms), current, stale, missing, oldest_gap,
                         target.isoformat() if target else None)


@dataclass(frozen=True)
class Settlement:
    price: float
    source: str
    after_hours: bool


def settlement_price(conn: sqlite3.Connection, symbol: str, session_date: str) -> Settlement | None:
    row = conn.execute(
        "SELECT close, after_hours FROM engine_daily_closes WHERE symbol=? AND session_date=?",
        (symbol.upper(), session_date),
    ).fetchone()
    if row is None:
        return None
    return Settlement(float(row[0]), "THETADATA_EOD", bool(row[1]))
