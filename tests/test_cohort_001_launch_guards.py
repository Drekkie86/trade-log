"""
Tests for the Cohort 001 launch guards added by preregistration
amendment 001.

These deliberately test the pure decision logic and the database-lock
precondition. They do not touch Git, the network or a provider, so they
run in the normal suite.

The Git-tracking guard (amendment 001 A1) is intentionally not unit
tested here: it asserts a property of the repository itself, and a test
that stubbed Git would assert nothing useful. It is exercised every time
the launcher runs, which is the only place it matters.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parents[1]

if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import run_cohort_001 as launcher  # noqa: E402


# ---------------------------------------------------------------------
# Amendment 001 A2 — previous-run gate
# ---------------------------------------------------------------------

def counts(
    *,
    completed: int = 0,
    failed: int = 0,
    invalid: int = 0,
) -> dict[str, int]:
    return {
        "COMPLETED": completed,
        "FAILED": failed,
        "INVALID": invalid,
    }


def test_first_collection_is_allowed():
    allowed, _ = launcher.evaluate_previous_run_gate(
        counts(),
        allow_retry_after_invalid=False,
    )
    assert allowed is True


def test_completed_run_blocks_even_with_retry_flag():
    allowed, reason = launcher.evaluate_previous_run_gate(
        counts(completed=1),
        allow_retry_after_invalid=True,
    )
    assert allowed is False
    assert "COMPLETED" in reason


def test_failed_run_is_never_retryable():
    """
    FAILED means the Massive universe fetch failed. Amendment 001 A2
    makes that a human-diagnosis condition, not an automatic retry.
    """
    allowed, reason = launcher.evaluate_previous_run_gate(
        counts(failed=1),
        allow_retry_after_invalid=True,
    )
    assert allowed is False
    assert "FAILED" in reason


def test_invalid_run_blocks_without_the_explicit_flag():
    allowed, reason = launcher.evaluate_previous_run_gate(
        counts(invalid=1),
        allow_retry_after_invalid=False,
    )
    assert allowed is False
    assert "--allow-retry-after-invalid" in reason


@pytest.mark.parametrize("invalid", [1, 2])
def test_invalid_runs_may_be_superseded_below_the_attempt_limit(invalid):
    allowed, reason = launcher.evaluate_previous_run_gate(
        counts(invalid=invalid),
        allow_retry_after_invalid=True,
    )
    assert allowed is True
    assert str(invalid) in reason


def test_third_invalid_attempt_blocks_a_fourth_launch():
    """
    Three INVALID attempts are the total maximum. After three, stop.
    """
    allowed, reason = launcher.evaluate_previous_run_gate(
        counts(invalid=launcher.MAX_INVALID_ATTEMPTS),
        allow_retry_after_invalid=True,
    )
    assert allowed is False
    assert "diagnose" in reason.lower()


def test_completed_takes_precedence_over_invalid():
    allowed, reason = launcher.evaluate_previous_run_gate(
        counts(completed=1, invalid=1),
        allow_retry_after_invalid=True,
    )
    assert allowed is False
    assert "COMPLETED" in reason


# ---------------------------------------------------------------------
# Status counting and supersession ids
# ---------------------------------------------------------------------

def _runs_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE research_runs (
            id        INTEGER PRIMARY KEY,
            cohort_id TEXT NOT NULL,
            status    TEXT NOT NULL
        );
        """
    )


def _insert(connection, cohort_id, status):
    connection.execute(
        "INSERT INTO research_runs (cohort_id, status) VALUES (?, ?);",
        (cohort_id, status),
    )


@pytest.fixture
def runs_db():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    _runs_table(connection)
    yield connection
    connection.close()


def test_status_counts_ignore_non_terminal_runs(runs_db):
    for status in [
        "STARTED",
        "COLLECTING",
        "COMPLETED",
        "INVALID",
        "INVALID",
    ]:
        _insert(runs_db, launcher.COHORT_ID, status)

    result = launcher.terminal_run_status_counts(runs_db)

    assert result == {
        "COMPLETED": 1,
        "FAILED": 0,
        "INVALID": 2,
    }


def test_status_counts_ignore_other_cohorts(runs_db):
    _insert(runs_db, launcher.COHORT_ID, "INVALID")
    _insert(runs_db, "COHORT_002_SOMETHING_ELSE", "COMPLETED")

    result = launcher.terminal_run_status_counts(runs_db)

    assert result["COMPLETED"] == 0
    assert result["INVALID"] == 1


def test_superseded_ids_are_ordered_and_invalid_only(runs_db):
    _insert(runs_db, launcher.COHORT_ID, "INVALID")
    _insert(runs_db, launcher.COHORT_ID, "COLLECTING")
    _insert(runs_db, launcher.COHORT_ID, "INVALID")

    assert launcher.superseded_invalid_run_ids(runs_db) == [1, 3]




def test_run_notes_record_superseded_ids_and_code_identity():
    notes = launcher.build_run_notes(
        superseded_run_ids=[2, 5],
        launcher_blob="abc123",
        amendment_blob="def456",
    )

    assert "supersedes_invalid_run_ids=2,5" in notes
    assert "launcher_blob=abc123" in notes
    assert "amendment_001_blob=def456" in notes


def test_first_run_notes_do_not_claim_supersession():
    notes = launcher.build_run_notes(
        superseded_run_ids=[],
        launcher_blob="abc123",
        amendment_blob="def456",
    )

    assert "supersedes_invalid_run_ids" not in notes


# ---------------------------------------------------------------------
# Amendment 001 A3 — database-lock precondition
# ---------------------------------------------------------------------

def test_writable_database_passes(tmp_path):
    db_path = tmp_path / "probe.db"
    sqlite3.connect(db_path).close()

    launcher.require_database_writable(db_path)


def test_locked_database_is_detected(tmp_path):
    """
    The whole collection runs in one write transaction. A second holder
    would otherwise surface as 'database is locked' partway through.
    """
    db_path = tmp_path / "probe.db"

    holder = sqlite3.connect(db_path)
    holder.execute("CREATE TABLE t (x INTEGER);")
    holder.execute("BEGIN EXCLUSIVE;")

    try:
        with pytest.raises(RuntimeError, match="locked"):
            launcher.require_database_writable(db_path)
    finally:
        holder.execute("ROLLBACK;")
        holder.close()


# ---------------------------------------------------------------------
# Amendment 001 A1 — the required-path list must stay honest
# ---------------------------------------------------------------------

def test_required_tracked_paths_all_exist():
    missing = [
        path
        for path in launcher.REQUIRED_TRACKED_PATHS
        if not (BASE_DIR / path).exists()
    ]
    assert not missing, f"listed but absent: {missing}"


def test_launcher_and_preregistration_are_required():
    assert "run_cohort_001.py" in launcher.REQUIRED_TRACKED_PATHS
    assert (
        "research/cohort_001_preregistration_v2.md"
        in launcher.REQUIRED_TRACKED_PATHS
    )
    assert (
        "research/cohort_001_preregistration_v2_amendment_001.md"
        in launcher.REQUIRED_TRACKED_PATHS
    )


def test_amendment_blob_is_pinned():
    assert len(launcher.EXPECTED_AMENDMENT_GIT_BLOB) == 40
    assert "FILLED_BY_PATCH" not in (
        launcher.EXPECTED_AMENDMENT_GIT_BLOB
    )
