"""Operator-only date/time rendering for Antwerp (Europe/Brussels).

Keep UTC instants untouched in databases, audit records, sort keys and APIs.
Never reinterpret a naive instant as local time; its timezone is unknown.
"""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

OPERATOR_TIMEZONE = ZoneInfo("Europe/Brussels")
TIMEZONE_LABEL = "Europe/Brussels (CET/CEST)"
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _aware_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        value_dt = value
    elif isinstance(value, str):
        try:
            value_dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if value_dt.tzinfo is None or value_dt.utcoffset() is None:
        return None
    return value_dt.astimezone(OPERATOR_TIMEZONE)


def format_local_datetime(value: object, *, weekday: bool = False) -> str:
    """Readable local clock time with DST-correct CET/CEST suffix."""
    if value is None or value == "":
        return "—"
    converted = _aware_datetime(value)
    if converted is None:
        return "Time zone unknown" if isinstance(value, (datetime, str)) else "—"
    prefix = f"{WEEKDAYS[converted.weekday()]} " if weekday else ""
    return (
        f"{prefix}{converted.day} {MONTHS[converted.month - 1]} {converted.year}, "
        f"{converted:%H:%M} {converted.tzname()}"
    )


def format_calendar_date(value: object) -> str:
    """Session dates are dates, never midnight instants to shift across zones."""
    if value is None or value == "":
        return "—"
    if isinstance(value, datetime):
        return "Time zone unknown"  # A datetime is not a pure calendar date.
    if isinstance(value, date):
        day = value
    elif isinstance(value, str):
        try:
            day = date.fromisoformat(value.strip())
        except ValueError:
            return str(value)
    else:
        return str(value)
    return f"{day.day} {MONTHS[day.month - 1]} {day.year}"


def is_operator_datetime_column(name: object) -> bool:
    """Only known instant fields, never dates, IDs or numeric durations."""
    col = str(name).strip().lower()
    return (
        col.endswith("_at")
        or col in {"scheduled_for", "heartbeat_at", "timestamp", "last_timestamp"}
        or col.endswith("_timestamp")
        or col.endswith("_timestamp_utc")
    )


def is_operator_date_column(name: object) -> bool:
    col = str(name).strip().lower()
    return col.endswith("_date") or col in {"session_date", "trading_date"}
