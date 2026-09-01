from datetime import datetime

import pytest
from zoneinfo import ZoneInfo

from src.research.deterministic_scanner import (
    DeterministicScannerError,
    _quote_age_seconds,
)
from src.research.live_pipeline import (
    LivePipelineError,
    attach_quote_ages,
)

NEW_YORK = ZoneInfo("America/New_York")


def test_live_pipeline_tolerates_real_observed_theta_skew():
    observed_at = datetime(
        2026, 9, 1, 13, 15, 0,
        tzinfo=NEW_YORK,
    )

    rows = (
        {
            "raw_timestamp":
                "2026-09-01T13:15:56.745",
        },
    )

    enriched = attach_quote_ages(
        rows,
        observed_at=observed_at,
    )

    assert enriched[0]["quote_age_seconds"] == 0.0


def test_live_pipeline_rejects_large_future_timestamp():
    observed_at = datetime(
        2026, 9, 1, 13, 15, 0,
        tzinfo=NEW_YORK,
    )

    rows = (
        {
            "raw_timestamp":
                "2026-09-01T13:17:00.000",
        },
    )

    with pytest.raises(
        LivePipelineError,
        match="materially in the future",
    ):
        attach_quote_ages(
            rows,
            observed_at=observed_at,
        )


def test_persisted_scanner_uses_same_tolerance():
    assert _quote_age_seconds(
        captured_at="2026-09-01T13:15:00-04:00",
        quote_at="2026-09-01T13:15:56.745",
    ) == 0.0


def test_persisted_scanner_rejects_large_future_timestamp():
    with pytest.raises(
        DeterministicScannerError,
        match="materially .*future",
    ):
        _quote_age_seconds(
            captured_at="2026-09-01T13:15:00-04:00",
            quote_at="2026-09-01T13:17:00.000",
        )
