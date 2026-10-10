"""Operator-facing Antwerp local time, without modifying stored UTC evidence."""
from pathlib import Path

from src.ui.datetime_display import (
    TIMEZONE_LABEL,
    format_calendar_date,
    format_local_datetime,
    is_operator_datetime_column,
    is_operator_date_column,
)


def test_summer_timestamp_is_cest_not_fixed_cet():
    assert format_local_datetime("2026-10-10T15:20:42Z") == "10 Oct 2026, 17:20 CEST"
    assert TIMEZONE_LABEL == "Europe/Brussels (CET/CEST)"


def test_winter_timestamp_is_cet():
    assert format_local_datetime("2026-12-10T15:20:42Z") == "10 Dec 2026, 16:20 CET"


def test_spring_clock_jump_does_not_show_nonexistent_two_am():
    assert format_local_datetime("2026-03-29T00:30:00Z") == "29 Mar 2026, 01:30 CET"
    assert format_local_datetime("2026-03-29T01:30:00Z") == "29 Mar 2026, 03:30 CEST"


def test_autumn_repeated_clock_hour_is_unambiguous():
    assert format_local_datetime("2026-10-25T00:30:00Z") == "25 Oct 2026, 02:30 CEST"
    assert format_local_datetime("2026-10-25T01:30:00Z") == "25 Oct 2026, 02:30 CET"


def test_offset_aware_provider_instant_converts_to_local():
    assert format_local_datetime("2026-10-10T11:20:00-04:00", weekday=True) == (
        "Sat 10 Oct 2026, 17:20 CEST"
    )


def test_naive_and_invalid_timestamp_never_falsely_assumed_local():
    assert format_local_datetime("2026-10-10T15:20:42") == "Time zone unknown"
    assert format_local_datetime("invalid") == "Time zone unknown"
    assert format_local_datetime(None) == "—"


def test_pure_calendar_dates_are_not_shifted():
    assert format_calendar_date("2026-10-05") == "5 Oct 2026"
    assert format_calendar_date("2026-12-31") == "31 Dec 2026"


def test_columns_restrict_conversion_to_instants_and_dates():
    assert is_operator_datetime_column("scheduled_for")
    assert is_operator_datetime_column("observed_at")
    assert is_operator_datetime_column("quote_at")
    assert is_operator_datetime_column("latest_mark_at")
    assert not is_operator_datetime_column("us_session_date")
    assert not is_operator_datetime_column("quote_age_seconds")
    assert is_operator_date_column("us_session_date")


def test_dashboard_displays_local_time_without_changing_source_data():
    app = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")
    assert "frame[column] = frame[column].map(format_local_datetime)" in app
    assert "frame[column] = frame[column].map(format_calendar_date)" in app
    assert 'format_local_datetime(market_clock.get("next_sample_at"))' in app
    assert 'format_local_datetime(last_at)' in app
    assert 'dt.tz_convert("Europe/Brussels")' in app
    assert "st.caption(f\"All displayed times: {TIMEZONE_LABEL}" in app
