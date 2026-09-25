from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from src.research.universe_profiles import (
    LIQUID_US_RESEARCH_V1,
    select_symbol_batch,
    symbols_for_profile,
)


NY = ZoneInfo("America/New_York")


def test_liquid_us_profile_has_48_unique_symbols():
    assert len(LIQUID_US_RESEARCH_V1) == 48
    assert len(set(LIQUID_US_RESEARCH_V1)) == 48


def test_profile_lookup_is_case_insensitive():
    assert symbols_for_profile("liquid_us_research_v1") == list(
        LIQUID_US_RESEARCH_V1
    )


def test_unknown_profile_fails_closed():
    with pytest.raises(ValueError, match="Unknown Christiania universe profile"):
        symbols_for_profile("unknown")


def test_four_rotating_batches_cover_profile_once():
    observed = []

    for hour, minute in (
        (9, 45),
        (10, 0),
        (10, 15),
        (10, 30),
    ):
        batch = select_symbol_batch(
            symbols=list(LIQUID_US_RESEARCH_V1),
            scheduled_for=datetime(
                2026,
                9,
                25,
                hour,
                minute,
                tzinfo=NY,
            ),
            batch_size=12,
            interval_minutes=15,
            profile="LIQUID_US_RESEARCH_V1",
        )
        assert batch.batch_size == 12
        assert batch.batch_count == 4
        observed.extend(batch.symbols)

    assert tuple(observed) == LIQUID_US_RESEARCH_V1
    assert len(set(observed)) == 48


def test_rotation_restarts_after_four_slots():
    first = select_symbol_batch(
        symbols=list(LIQUID_US_RESEARCH_V1),
        scheduled_for=datetime(2026, 9, 25, 9, 45, tzinfo=NY),
        batch_size=12,
        interval_minutes=15,
    )
    fifth = select_symbol_batch(
        symbols=list(LIQUID_US_RESEARCH_V1),
        scheduled_for=datetime(2026, 9, 25, 10, 45, tzinfo=NY),
        batch_size=12,
        interval_minutes=15,
    )

    assert first.batch_index == 0
    assert fifth.batch_index == 0
    assert fifth.symbols == first.symbols
