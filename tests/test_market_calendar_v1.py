from datetime import date

from src.operations.market_calendar import (
    get_market_session,
)


def test_labor_day_is_not_a_session():
    assert get_market_session(
        date(2026, 9, 7)
    ) is None


def test_regular_session_keeps_15_minute_edges():
    session = get_market_session(
        date(2026, 9, 4)
    )

    assert session is not None
    assert session.open_at.endswith("09:30:00-04:00")
    assert session.close_at.endswith("16:00:00-04:00")
    assert session.sample_window_start.endswith("09:45:00-04:00")
    assert session.sample_window_end.endswith("15:45:00-04:00")
    assert session.is_early_close is False


def test_thanksgiving_friday_early_close_stops_at_1245():
    session = get_market_session(
        date(2026, 11, 27)
    )

    assert session is not None
    assert session.close_at.endswith("13:00:00-05:00")
    assert session.sample_window_end.endswith("12:45:00-05:00")
    assert session.is_early_close is True
