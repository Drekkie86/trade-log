from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from src.research.live_pipeline import (
    LivePipelineError,
    attach_quote_ages,
    build_live_join,
    diagnose_admission,
    parse_thetadata_market_timestamp,
)

NY = ZoneInfo("America/New_York")


def test_naive_theta_timestamp_is_interpreted_as_new_york():
    parsed = parse_thetadata_market_timestamp(
        "2026-08-31T15:01:46.820"
    )

    assert parsed.tzinfo is not None
    assert parsed.utcoffset().total_seconds() == -4 * 3600


def test_quote_age_is_calculated_from_quote_timestamp():
    rows = (
        {
            "underlying": "AAPL",
            "expiration": "2026-09-14",
            "strike": 245.0,
            "right": "C",
            "raw_timestamp":
                "2026-08-31T15:01:46.820",
        },
    )

    observed_at = datetime(
        2026,
        8,
        31,
        15,
        1,
        49,
        820000,
        tzinfo=NY,
    )

    enriched = attach_quote_ages(
        rows,
        observed_at=observed_at,
    )

    assert enriched[0][
        "quote_age_seconds"
    ] == pytest.approx(3.0)


def test_missing_timestamp_yields_unknown_freshness():
    refs = [
        {
            "id": 1,
            "underlying": "AAPL",
            "expiration": "2026-09-14",
            "strike": 245.0,
            "right": "C",
        }
    ]

    joined = build_live_join(
        reference_contracts=refs,
        quote_rows=(
            {
                "underlying": "AAPL",
                "expiration": "2026-09-14",
                "strike": 245.0,
                "right": "C",
            },
        ),
        greek_rows=(
            {
                "underlying": "AAPL",
                "expiration": "2026-09-14",
                "strike": 245.0,
                "right": "C",
                "iv_error": 0.001,
            },
        ),
        observed_at=datetime(
            2026,
            8,
            31,
            15,
            1,
            49,
            tzinfo=NY,
        ),
    )

    diagnostic = diagnose_admission(
        joined
    )[0]

    assert diagnostic.structurally_ready is False
    assert "QUOTE_NOT_FRESH" in (
        diagnostic.blocking_reasons
    )


def test_stale_quote_blocks_even_with_good_greek():
    refs = [
        {
            "id": 1,
            "underlying": "AAPL",
            "expiration": "2026-09-14",
            "strike": 245.0,
            "right": "C",
        }
    ]

    joined = build_live_join(
        reference_contracts=refs,
        quote_rows=(
            {
                "underlying": "AAPL",
                "expiration": "2026-09-14",
                "strike": 245.0,
                "right": "C",
                "raw_timestamp":
                    "2026-08-31T14:59:00",
            },
        ),
        greek_rows=(
            {
                "underlying": "AAPL",
                "expiration": "2026-09-14",
                "strike": 245.0,
                "right": "C",
                "iv_error": 0.001,
            },
        ),
        observed_at=datetime(
            2026,
            8,
            31,
            15,
            1,
            0,
            tzinfo=NY,
        ),
    )

    diagnostic = diagnose_admission(
        joined
    )[0]

    assert diagnostic.quote_freshness.value == "STALE"
    assert diagnostic.greek_quality.value == "GOOD"
    assert diagnostic.structurally_ready is False


def test_fresh_quote_and_good_greek_are_structurally_ready():
    refs = [
        {
            "id": 1,
            "underlying": "AAPL",
            "expiration": "2026-09-14",
            "strike": 245.0,
            "right": "C",
        }
    ]

    joined = build_live_join(
        reference_contracts=refs,
        quote_rows=(
            {
                "underlying": "AAPL",
                "expiration": "2026-09-14",
                "strike": 245.0,
                "right": "C",
                "raw_timestamp":
                    "2026-08-31T15:00:55",
            },
        ),
        greek_rows=(
            {
                "underlying": "AAPL",
                "expiration": "2026-09-14",
                "strike": 245.0,
                "right": "C",
                "iv_error": 0.001,
            },
        ),
        observed_at=datetime(
            2026,
            8,
            31,
            15,
            1,
            0,
            tzinfo=NY,
        ),
    )

    diagnostic = diagnose_admission(
        joined
    )[0]

    assert diagnostic.structurally_ready is True


def test_future_quote_timestamp_fails_closed():
    rows = (
        {
            "underlying": "AAPL",
            "expiration": "2026-09-14",
            "strike": 245.0,
            "right": "C",
            "raw_timestamp":
                "2026-08-31T15:03:00",
        },
    )

    with pytest.raises(
        LivePipelineError,
        match="future",
    ):
        attach_quote_ages(
            rows,
            observed_at=datetime(
                2026,
                8,
                31,
                15,
                1,
                0,
                tzinfo=NY,
            ),
        )
