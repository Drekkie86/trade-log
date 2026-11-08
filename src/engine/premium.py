"""The implied-variance history behind the risk-premium estimate.

For every underlying and past session the engine keeps the 30-day constant-
maturity implied vol at the close (``engine_iv_history``), taken from the
ThetaData EOD option chain of that session. Paired with the realised variance
of the 21 sessions that followed (``engine_daily_closes``, split-adjusted) it
gives lambda, the ratio the REAL_WORLD distribution is built from.

The history is backfilled a bounded number of sessions per engine step and
kept current afterwards (one request per symbol per session). A session whose
chain cannot yield a point is stored with a NULL so it is not refetched. Until
an underlying has MIN_PREMIUM_OBSERVATIONS matched sessions it cannot pass:
MODEL_UNAVAILABLE, never a guess.
"""
from __future__ import annotations

import os
import sqlite3
from datetime import UTC, date, datetime, timedelta
from typing import Iterable

from src.engine.chains import constant_maturity_point
from src.engine.eod import fetch_eod_chain_rows, quotes_from_eod_rows, session_close
from src.engine.history import (
    adjusted_closes, last_completed_session, raw_close_series, stock_history_first_date,
)
from src.engine.models import (
    MIN_PREMIUM_OBSERVATIONS, PREMIUM_WINDOW_SESSIONS, REALISED_HORIZON_SESSIONS,
    ModelUnavailable, RiskPremium, estimate_risk_premium,
)

# Sessions of implied history worth holding: the estimation window plus the
# realised horizon, with slack for holidays. Expressed in calendar days for the
# calendar lookup.
HISTORY_CALENDAR_DAYS = 800
CHAIN_MIN_DTE = 7
CHAIN_MAX_DTE = 45
DEFAULT_BACKFILL_PER_STEP = 120


def backfill_budget() -> int:
    try:
        return max(0, int(os.environ.get("CHRISTIANIA_IV_BACKFILL_PER_STEP", DEFAULT_BACKFILL_PER_STEP)))
    except ValueError:
        return DEFAULT_BACKFILL_PER_STEP


def iv_point_from_rows(rows: Iterable[dict], session: date) -> float | None:
    """30-day constant-maturity implied vol from one session's EOD chain rows."""
    quotes = quotes_from_eod_rows(rows, session)
    if not quotes:
        return None
    return constant_maturity_point(quotes, session_close(session),
                                   min_dte=CHAIN_MIN_DTE, max_dte=CHAIN_MAX_DTE)


# ------------------------------------------------------------------- storage
def store_iv_point(conn: sqlite3.Connection, symbol: str, session: date, iv: float | None, *,
                   source: str, fetched_at: str) -> None:
    with conn:
        conn.execute(
            """INSERT OR IGNORE INTO engine_iv_history (symbol, session_date, iv30, source, fetched_at)
               VALUES (?, ?, ?, ?, ?)""",
            (symbol.upper(), session.isoformat(), iv, source, fetched_at),
        )


def iv_history(conn: sqlite3.Connection, symbol: str, *, before: date) -> list[tuple[str, float]]:
    """Ascending (session_date, iv30) strictly before ``before``; NULL points skipped."""
    rows = conn.execute(
        """SELECT session_date, iv30 FROM engine_iv_history
           WHERE symbol=? AND session_date<? AND iv30 IS NOT NULL ORDER BY session_date""",
        (symbol.upper(), before.isoformat()),
    ).fetchall()
    return [(str(r[0]), float(r[1])) for r in rows]


def iv_history_counts(conn: sqlite3.Connection, symbols: Iterable[str]) -> dict[str, int]:
    out = {s.upper(): 0 for s in symbols}
    for r in conn.execute(
        "SELECT symbol, COUNT(*) FROM engine_iv_history WHERE iv30 IS NOT NULL GROUP BY symbol"
    ):
        if str(r[0]) in out:
            out[str(r[0])] = int(r[1])
    return out


def refresh_iv_history(conn: sqlite3.Connection, theta_client, symbols: Iterable[str], *,
                       now: datetime, max_requests: int | None = None,
                       calendar=None) -> dict[str, str]:
    """Fetch the EOD chain of every missing session, newest first, within the budget.

    Returns a status per symbol: CURRENT, FETCHED:<n>, PARTIAL:<n> (budget ran
    out) or FAILED:<error>.
    """
    from src.operations.market_calendar import get_xnys_calendar

    cal = calendar or get_xnys_calendar()
    target = last_completed_session(now, calendar)
    status: dict[str, str] = {}
    if target is None:
        return status
    first = max(target - timedelta(days=HISTORY_CALENDAR_DAYS), stock_history_first_date())
    wanted = [d.date() for d in cal.sessions_in_range(first.isoformat(), target.isoformat())]
    names = sorted({s.upper() for s in symbols})
    if not wanted:
        return {s: "CURRENT" for s in names}
    fetched_at = now.astimezone(UTC).isoformat().replace("+00:00", "Z")
    budget = backfill_budget() if max_requests is None else max_requests
    missing: dict[str, list[date]] = {}
    for symbol in names:
        have = {str(r[0]) for r in conn.execute(
            "SELECT session_date FROM engine_iv_history WHERE symbol=? AND session_date>=?",
            (symbol, wanted[0].isoformat()),
        )}
        todo = [d for d in reversed(wanted) if d.isoformat() not in have]
        if not todo:
            status[symbol] = "CURRENT"
        else:
            missing[symbol] = todo
    # Round-robin so every underlying advances each step.
    fetched = {s: 0 for s in missing}
    failed: set[str] = set()
    while budget > 0 and any(missing[s] for s in missing if s not in failed):
        for symbol in list(missing):
            if symbol in failed or not missing[symbol] or budget <= 0:
                continue
            session = missing[symbol].pop(0)
            budget -= 1
            try:
                rows = fetch_eod_chain_rows(theta_client, symbol, session, max_dte=CHAIN_MAX_DTE)
                point = iv_point_from_rows(rows, session)
            except Exception as exc:  # provider failure must not stop the engine
                status[symbol] = f"FAILED:{type(exc).__name__}"
                failed.add(symbol)
                continue
            store_iv_point(conn, symbol, session, point, source="THETADATA_EOD", fetched_at=fetched_at)
            fetched[symbol] += 1
    for symbol in missing:
        if symbol in failed:
            continue
        status[symbol] = (f"FETCHED:{fetched[symbol]}" if not missing[symbol]
                          else f"PARTIAL:{fetched[symbol]}")
    return status


# ----------------------------------------------------------------- estimate
def dated_adjusted_closes(conn: sqlite3.Connection, symbol: str, *, before: date) -> list[tuple[str, float]]:
    raw = raw_close_series(conn, symbol, before=before)
    return list(zip((d for d, _ in raw), adjusted_closes(raw)))


def risk_premium_for(conn: sqlite3.Connection, symbol: str, *, before: date) -> RiskPremium | None:
    """The trailing risk premium of ``symbol`` from stored history, or None."""
    points = iv_history(conn, symbol, before=before)
    if len(points) < MIN_PREMIUM_OBSERVATIONS:
        return None
    try:
        return estimate_risk_premium(points, dated_adjusted_closes(conn, symbol, before=before),
                                     before=before.isoformat())
    except ModelUnavailable:
        return None


def premium_status(conn: sqlite3.Connection, symbols: Iterable[str], *, before: date) -> dict[str, dict]:
    """Per symbol: stored points, matched observations and lambda (or why not)."""
    out: dict[str, dict] = {}
    for symbol in sorted({s.upper() for s in symbols}):
        points = iv_history(conn, symbol, before=before)
        try:
            prem = estimate_risk_premium(points, dated_adjusted_closes(conn, symbol, before=before),
                                         before=before.isoformat())
            out[symbol] = {"points": len(points), "observations": prem.observations,
                           "ratio": round(prem.ratio, 3), "ready": True}
        except ModelUnavailable as exc:
            out[symbol] = {"points": len(points), "observations": 0, "ratio": None,
                           "ready": False, "reason": str(exc)}
    return out


def sessions_needed() -> int:
    """Sessions of implied history before an underlying can be scored."""
    return MIN_PREMIUM_OBSERVATIONS + REALISED_HORIZON_SESSIONS


__all__ = [
    "HISTORY_CALENDAR_DAYS", "PREMIUM_WINDOW_SESSIONS", "backfill_budget", "iv_point_from_rows",
    "store_iv_point", "iv_history", "iv_history_counts", "refresh_iv_history",
    "dated_adjusted_closes", "risk_premium_for", "premium_status", "sessions_needed",
]
