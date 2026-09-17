from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_fast_current_database_guard_preserves_exact_active_schema_contract():
    receiver = (
        ROOT / "deploy/receive_release.sh"
    ).read_text(encoding="utf-8")

    assert "validate_current_database_metadata()" in receiver
    assert "inspect_database(deep_integrity=False)" in receiver
    assert "health.schema_version != EXPECTED_SCHEMA_VERSION" in receiver
    assert 'health.journal_mode != "wal"' in receiver
    assert 'phase_start "Validating current database schema/WAL metadata"' in receiver


def test_release_path_keeps_authoritative_deep_database_checks():
    receiver = (
        ROOT / "deploy/receive_release.sh"
    ).read_text(encoding="utf-8")
    release_db = (
        ROOT / "christiania_release_database.py"
    ).read_text(encoding="utf-8")
    preflight = (
        ROOT / "christiania_deploy_preflight.py"
    ).read_text(encoding="utf-8")

    assert receiver.count("--metadata-db-check") == 2
    assert "PRAGMA integrity_check;" in release_db
    assert "PRAGMA foreign_key_check;" in release_db
    assert "_verify_database(database, expected_version=EXPECTED_SCHEMA_VERSION)" in release_db
    assert "deep_database: bool = True" in preflight


def test_long_database_safety_phases_have_heartbeat_progress():
    release_db = (
        ROOT / "christiania_release_database.py"
    ).read_text(encoding="utf-8")

    assert "HEARTBEAT_INTERVAL_SECONDS = 15.0" in release_db
    assert "still running; elapsed={elapsed}s" in release_db
    assert 'outcome = "completed" if succeeded else "stopped"' in release_db
