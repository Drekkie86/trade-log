"""Regressions for the October 2026 misleading green daemon badge."""
from pathlib import Path

from src.ui.components import _tone_for_state


def test_missing_daemon_lease_is_not_green():
    assert _tone_for_state("NO_DAEMON_LEASE") == "bad"
    assert _tone_for_state("STALE_DAEMON_LEASE") == "bad"


def test_negative_health_tokens_do_not_match_positive_substrings():
    assert _tone_for_state("UNHEALTHY") == "bad"
    assert _tone_for_state("NOT_READY") == "bad"
    assert _tone_for_state("HEALTHY") == "good"


