"""Truthful, bounded presentation of recorded daemon cycles.

This module NEVER infers a completed research cycle from systemd uptime.
Missed sessions are informational: a day without a recorded iteration does
not, by itself, prove a trade, result, or root cause.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from src.operations.market_calendar import get_market_session

NEW_YORK = ZoneInfo("America/New_York")
MAX_CALENDAR_DAYS = 90


def _parse_utc(value: object) -> datetime | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def summarize_daemon_activity(
    recent_iterations: list[dict[str, object]],
    *,
    daemon_state: str,
    recorded_session_dates: list[str] | None = None,
    observed_at: datetime | None = None,
) -> dict[str, object]:
    """Classify the history independently of the present daemon lease."""
    now = observed_at or datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError("observed_at must have a timezone")
    now = now.astimezone(UTC)

    latest = max(
        (
            (_parse_utc(row.get("scheduled_for")), row)
            for row in recent_iterations
        ),
        key=lambda item: item[0] or datetime.min.replace(tzinfo=UTC),
        default=(None, {}),
    )
    last_scheduled_at, last_row = latest
    last_completed_at = _parse_utc(last_row.get("completed_at"))

    missing_dates: list[str] = []
    window_truncated = False
    # The timestamped 25-cycle plot is short by design. A separately bounded
    # indexed history of session dates preserves a missing-session alert after
    # the daemon resumes and old points roll out of that plot.
    observed_days = {
        date.fromisoformat(d)
        for d in (recorded_session_dates or [])
        if isinstance(d, str) and len(d) == 10
    }
    if observed_days:
        first_day = min(observed_days) + timedelta(days=1)
    elif last_scheduled_at is not None and recorded_session_dates is None:
        first_day = last_scheduled_at.astimezone(NEW_YORK).date() + timedelta(days=1)
        observed_days = {last_scheduled_at.astimezone(NEW_YORK).date()}
    else:
        first_day = None

    if first_day is not None:
        today = now.astimezone(NEW_YORK).date()
        if (today - first_day).days > MAX_CALENDAR_DAYS:
            first_day = today - timedelta(days=MAX_CALENDAR_DAYS)
            window_truncated = True
        current: date = first_day
        while current <= today:
            session = get_market_session(current)
            if session is not None and current not in observed_days:
                close = datetime.fromisoformat(session.close_at).astimezone(UTC)
                # Allow post-close settling. Incomplete current sessions are
                # not labelled missing; weekends/holidays are ignored.
                if close + timedelta(minutes=30) <= now:
                    missing_dates.append(current.isoformat())
            current += timedelta(days=1)

    state = str(daemon_state or "UNKNOWN").upper()
    return {
        "live_healthy": state == "HEALTHY",
        "daemon_state": state,
        "last_scheduled_at": (
            last_scheduled_at.isoformat().replace("+00:00", "Z")
            if last_scheduled_at else None
        ),
        "last_completed_at": (
            last_completed_at.isoformat().replace("+00:00", "Z")
            if last_completed_at else None
        ),
        "latest_recorded_status": last_row.get("status"),
        "missing_completed_sessions": missing_dates,
        "window_truncated": window_truncated,
    }
