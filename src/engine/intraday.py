"""Intraday price history for the 0DTE lane.

A same-day option's remaining life is part of one session, so its models must
be built from *remaining-session* returns (price at this time of day to the
close), not from close-to-close returns scaled by a fraction. The overnight gap
is excluded and the intraday volatility pattern is taken from the data itself.

Source: ThetaData ``/v3/stock/history/ohlc`` 5-minute bars (Value tier and up),
stored per session in ``engine_intraday_sessions``. A next-day expiry pairs
each session's remaining return with the following session's close-to-close
return from ``engine_daily_closes``.
"""
from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

from src.engine.chains import NY
from src.engine.models import (
    EMPIRICAL, FAMILY_PRICE_HISTORY, VOL_FORECAST, Distribution, ModelUnavailable, lognormal,
)

BAR_INTERVAL = "5m"
BAR_MINUTES = 5
SESSIONS_WANTED = 60
MIN_SESSIONS = 40
MAX_REQUEST_DAYS = 28         # ThetaData: multi-day OHLC requests are limited to one month
EWMA_DECAY = 0.94
SESSION_OPEN_MINUTE = 9 * 60 + 30


@dataclass(frozen=True)
class IntradaySession:
    session_date: str
    minutes: tuple[int, ...]      # minute of day (New York) at which each bar ENDS
    closes: tuple[float, ...]

    def price_at(self, minute_of_day: int) -> float | None:
        """Close of the last bar that ended at or before ``minute_of_day``."""
        best = None
        for m, c in zip(self.minutes, self.closes):
            if m <= minute_of_day:
                best = c
            else:
                break
        return best

    @property
    def last_close(self) -> float:
        return self.closes[-1]


@dataclass(frozen=True)
class IntradayHistory:
    symbol: str
    sessions: tuple[IntradaySession, ...]           # ascending by date
    daily_closes: Mapping[str, float]               # session_date -> EOD close

    def remaining_returns(self, minute_of_day: int) -> list[tuple[str, float]]:
        out = []
        for s in self.sessions:
            px = s.price_at(minute_of_day)
            if px and px > 0 and s.last_close > 0:
                out.append((s.session_date, math.log(s.last_close / px)))
        return out

    def next_session_returns(self) -> dict[str, float]:
        dates = sorted(self.daily_closes)
        out = {}
        for d0, d1 in zip(dates, dates[1:]):
            c0, c1 = self.daily_closes[d0], self.daily_closes[d1]
            if c0 > 0 and c1 > 0:
                out[d0] = math.log(c1 / c0)
        return out


# ----------------------------------------------------------------- parsing
def _bar_minute(stamp: str) -> int | None:
    try:
        t = datetime.fromisoformat(str(stamp).strip())
    except ValueError:
        return None
    return t.hour * 60 + t.minute


def parse_ohlc_sessions(payload: Any) -> list[IntradaySession]:
    """Group 5-minute bars by session date; bar time is the bar's opening time."""
    rows = payload.get("response") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise ValueError("ThetaData OHLC payload is not a list")
    by_day: dict[str, list[tuple[int, float]]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        stamp = row.get("timestamp") or row.get("time") or row.get("date")
        close = row.get("close")
        if stamp is None or isinstance(close, bool):
            continue
        try:
            close = float(close)
            start = datetime.fromisoformat(str(stamp).strip())
        except (TypeError, ValueError):
            continue
        if not math.isfinite(close) or close <= 0:
            continue
        end_minute = start.hour * 60 + start.minute + BAR_MINUTES
        by_day.setdefault(start.date().isoformat(), []).append((end_minute, close))
    out = []
    for d in sorted(by_day):
        bars = sorted(by_day[d])
        if len(bars) < 30:          # a full session has 78 five-minute bars
            continue
        out.append(IntradaySession(d, tuple(m for m, _ in bars), tuple(c for _, c in bars)))
    return out


def fetch_ohlc_sessions(theta_client, symbol: str, start: date, end: date) -> list[IntradaySession]:
    payload = theta_client._get_payload(
        "/stock/history/ohlc",
        {"symbol": symbol.upper(), "start_date": start.strftime("%Y%m%d"),
         "end_date": end.strftime("%Y%m%d"), "interval": BAR_INTERVAL, "venue": "utp_cta"},
    )
    return parse_ohlc_sessions(payload)


# ----------------------------------------------------------------- storage
def stored_sessions(conn: sqlite3.Connection, symbol: str, since: str) -> list[IntradaySession]:
    rows = conn.execute(
        """SELECT session_date, bars_json FROM engine_intraday_sessions
           WHERE symbol=? AND session_date>=? ORDER BY session_date""",
        (symbol.upper(), since),
    ).fetchall()
    out = []
    for r in rows:
        bars = json.loads(r[1])
        out.append(IntradaySession(str(r[0]), tuple(int(m) for m, _ in bars),
                                   tuple(float(c) for _, c in bars)))
    return out


def refresh_intraday(conn: sqlite3.Connection, theta_client, symbols: Iterable[str], *,
                     now: datetime, sessions_wanted: int = SESSIONS_WANTED,
                     max_requests: int = 4, calendar=None) -> dict[str, str]:
    """Fetch missing completed sessions, newest first, at most ``max_requests`` calls."""
    from src.engine.history import last_completed_session
    from src.operations.market_calendar import get_xnys_calendar

    cal = calendar or get_xnys_calendar()
    target = last_completed_session(now, calendar)
    status: dict[str, str] = {}
    if target is None:
        return status
    wanted = [d.date() for d in cal.sessions_in_range(
        (target - timedelta(days=int(sessions_wanted * 1.6) + 10)).isoformat(), target.isoformat()
    )][-sessions_wanted:]
    fetched_at = now.astimezone(UTC).isoformat().replace("+00:00", "Z")
    budget = max_requests
    for symbol in sorted({s.upper() for s in symbols}):
        have = {r[0] for r in conn.execute(
            "SELECT session_date FROM engine_intraday_sessions WHERE symbol=? AND session_date>=?",
            (symbol, wanted[0].isoformat()),
        )}
        missing = [d for d in wanted if d.isoformat() not in have]
        if not missing:
            status[symbol] = "CURRENT"
            continue
        # Contiguous ranges of at most MAX_REQUEST_DAYS calendar days, newest first.
        ranges: list[tuple[date, date]] = []
        for d in reversed(missing):
            if ranges and (ranges[-1][1] - d).days < MAX_REQUEST_DAYS:
                ranges[-1] = (d, ranges[-1][1])
            else:
                ranges.append((d, d))
        inserted = 0
        for start, end in ranges:
            if budget <= 0:
                status[symbol] = f"PARTIAL:{inserted}"
                break
            budget -= 1
            try:
                sessions = fetch_ohlc_sessions(theta_client, symbol, start, end)
            except Exception as exc:  # provider failure must not stop the engine
                status[symbol] = f"FAILED:{type(exc).__name__}"
                break
            with conn:
                conn.executemany(
                    """INSERT OR IGNORE INTO engine_intraday_sessions
                       (symbol, session_date, bars_json, fetched_at) VALUES (?, ?, ?, ?)""",
                    [(symbol, s.session_date,
                      json.dumps([[m, c] for m, c in zip(s.minutes, s.closes)]), fetched_at)
                     for s in sessions],
                )
            inserted += len(sessions)
        else:
            status[symbol] = f"FETCHED:{inserted}"
    return status


def load_intraday_history(conn: sqlite3.Connection, symbol: str, *, before: date,
                          sessions_wanted: int = SESSIONS_WANTED) -> IntradayHistory:
    since = (before - timedelta(days=int(sessions_wanted * 1.6) + 10)).isoformat()
    sessions = [s for s in stored_sessions(conn, symbol, since) if s.session_date < before.isoformat()]
    closes = {
        str(r[0]): float(r[1]) for r in conn.execute(
            "SELECT session_date, close FROM engine_daily_closes WHERE symbol=? AND session_date>=?",
            (symbol.upper(), since),
        )
    }
    return IntradayHistory(symbol.upper(), tuple(sessions[-sessions_wanted:]), closes)


# -------------------------------------------------------------- distributions
def _ewma_variance(returns: Sequence[float], decay: float = EWMA_DECAY) -> float:
    r = np.asarray(returns, dtype=float)
    variance = float(np.var(r, ddof=1))
    for value in r:
        variance = decay * variance + (1.0 - decay) * float(value * value)
    return variance


def zero_dte_distributions(history: IntradayHistory, *, asof: datetime, expiration: str,
                           today: date) -> dict[str, Distribution]:
    """Forecast distributions for an expiry today or on the next session."""
    local = asof.astimezone(NY)
    minute = max(local.hour * 60 + local.minute, SESSION_OPEN_MINUTE + BAR_MINUTES)
    base = history.remaining_returns(minute)
    expiry = date.fromisoformat(expiration)
    if expiry == today:
        sample = [r for _, r in base]
        note = f"{len(sample)} sessions' returns from {local:%H:%M} NY to the close"
    elif expiry > today:
        nxt = history.next_session_returns()
        sample = [r + nxt[d] for d, r in base if d in nxt]
        note = f"{len(sample)} sessions' returns from {local:%H:%M} NY to the next close"
    else:
        raise ModelUnavailable("0DTE: expiry in the past")
    if len(sample) < MIN_SESSIONS:
        raise ModelUnavailable(f"0DTE: {len(sample)} intraday sessions, need {MIN_SESSIONS}")
    arr = np.asarray(sample, dtype=float)
    arr = arr - float(arr.mean())
    var = float(np.var(arr))
    if var <= 0:
        raise ModelUnavailable("0DTE: zero variance intraday history")
    shift = math.log(float(np.mean(np.exp(arr))))
    empirical = Distribution(EMPIRICAL, FAMILY_PRICE_HISTORY, np.sort(arr - shift), var, note)
    forecast = lognormal(VOL_FORECAST, FAMILY_PRICE_HISTORY, _ewma_variance(sample),
                         "EWMA of the same remaining-session returns")
    return {VOL_FORECAST: forecast, EMPIRICAL: empirical}
