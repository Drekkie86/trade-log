from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, time as clock_time, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

import exchange_calendars as xcals


NY = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")
XNYS_CALENDAR_NAME = "XNYS"
SESSION_EDGE_EXCLUSION = timedelta(minutes=15)


@dataclass(frozen=True)
class MarketSession:
    session_date: str
    open_at: str
    close_at: str
    sample_window_start: str
    sample_window_end: str
    is_early_close: bool

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class MarketClock:
    observed_at: str
    state: str
    session: MarketSession | None
    next_sample_at: str | None

    def as_dict(self) -> dict[str, object]:
        return {
            "observed_at": self.observed_at,
            "state": self.state,
            "session": (
                None
                if self.session is None
                else self.session.as_dict()
            ),
            "next_sample_at": self.next_sample_at,
        }


@lru_cache(maxsize=1)
def get_xnys_calendar():
    return xcals.get_calendar(
        XNYS_CALENDAR_NAME
    )


def _iso(moment: datetime) -> str:
    return moment.isoformat(
        timespec="seconds"
    )


def _calendar_moment(value) -> datetime:
    return value.to_pydatetime().astimezone(NY)


def get_market_session(
    session_date: date,
    *,
    edge_exclusion: timedelta = SESSION_EDGE_EXCLUSION,
    calendar=None,
) -> MarketSession | None:
    if edge_exclusion < timedelta(0):
        raise ValueError(
            "edge_exclusion cannot be negative."
        )

    market_calendar = (
        get_xnys_calendar()
        if calendar is None
        else calendar
    )
    key = session_date.isoformat()

    if not market_calendar.is_session(key):
        return None

    open_at = _calendar_moment(
        market_calendar.session_open(key)
    )
    close_at = _calendar_moment(
        market_calendar.session_close(key)
    )

    sample_start = (
        open_at + edge_exclusion
    )
    sample_end = (
        close_at - edge_exclusion
    )

    if sample_start > sample_end:
        raise RuntimeError(
            "Exchange session is shorter than the configured edge exclusions."
        )

    regular_close = datetime.combine(
        session_date,
        clock_time(16, 0),
        tzinfo=NY,
    )

    return MarketSession(
        session_date=key,
        open_at=_iso(open_at),
        close_at=_iso(close_at),
        sample_window_start=_iso(
            sample_start
        ),
        sample_window_end=_iso(
            sample_end
        ),
        is_early_close=(
            close_at < regular_close
        ),
    )


def session_sample_bounds(
    session_date: date,
    *,
    configured_start: clock_time,
    configured_end: clock_time,
    edge_exclusion: timedelta = SESSION_EDGE_EXCLUSION,
    calendar=None,
) -> tuple[datetime, datetime] | None:
    if configured_end < configured_start:
        raise ValueError(
            "configured_end cannot precede configured_start."
        )

    session = get_market_session(
        session_date,
        edge_exclusion=edge_exclusion,
        calendar=calendar,
    )

    if session is None:
        return None

    exchange_start = datetime.fromisoformat(
        session.sample_window_start
    )
    exchange_end = datetime.fromisoformat(
        session.sample_window_end
    )

    configured_start_at = datetime.combine(
        session_date,
        configured_start,
        tzinfo=NY,
    )
    configured_end_at = datetime.combine(
        session_date,
        configured_end,
        tzinfo=NY,
    )

    start = max(
        exchange_start,
        configured_start_at,
    )
    end = min(
        exchange_end,
        configured_end_at,
    )

    if start > end:
        return None

    return start, end


def market_clock_snapshot(
    *,
    now: datetime | None = None,
) -> MarketClock:
    observed = (
        datetime.now(NY)
        if now is None
        else now.astimezone(NY)
    )

    session = get_market_session(
        observed.date()
    )

    next_sample = None

    if session is None:
        state = "NON_SESSION_DAY"
    else:
        sample_start = datetime.fromisoformat(
            session.sample_window_start
        )
        sample_end = datetime.fromisoformat(
            session.sample_window_end
        )

        if observed < sample_start:
            state = "BEFORE_SAMPLE_WINDOW"
        elif observed <= sample_end:
            state = "ACTIVE_SAMPLE_WINDOW"
        else:
            state = "AFTER_SAMPLE_WINDOW"

    # Import lazily to avoid a module cycle: the daemon imports
    # session_sample_bounds from this module.
    from src.research.research_daemon import next_sampling_slot

    try:
        next_sample = _iso(
            next_sampling_slot(observed)
        )
    except RuntimeError:
        next_sample = None

    return MarketClock(
        observed_at=_iso(observed),
        state=state,
        session=session,
        next_sample_at=next_sample,
    )
