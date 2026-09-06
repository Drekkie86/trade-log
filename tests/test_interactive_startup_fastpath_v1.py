from __future__ import annotations

from pathlib import Path

from src.dashboard.read_model import load_command_deck
from src.operations.backup_recovery import inventory_backups_fast
from src.operations.sqlite_runtime import inspect_database


def test_fast_database_health_skips_deep_integrity_pragmas(db_path):
    health = inspect_database(db_path, deep_integrity=False)

    assert health.exists is True
    assert health.schema_version == health.expected_schema_version
    assert health.journal_mode == "wal"
    assert health.quick_check is None
    assert health.foreign_key_violation_count is None


def test_deep_database_health_remains_available(db_path):
    health = inspect_database(db_path)

    assert health.quick_check == "ok"
    assert health.foreign_key_violation_count == 0


def test_command_deck_fast_path_is_ready_without_deep_integrity_scan(db_path):
    deck = load_command_deck(
        db_path,
        include_provider_health=False,
        deep_integrity=False,
    )

    assert deck["ready"] is True
    assert deck["database"]["quick_check"] is None
    assert deck["database"]["foreign_key_violation_count"] is None


def test_fast_backup_inventory_never_claims_unverified_file_is_valid(tmp_path):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    bogus = backup_dir / "christiania_backup_20260906T000000Z.db"
    bogus.write_bytes(b"not a sqlite database")

    inventory = inventory_backups_fast(backup_dir)

    assert inventory.total_files == 1
    assert inventory.valid_files == 0
    assert inventory.invalid_files == 0
    assert inventory.latest_valid_path is None
    assert inventory.entries[0].state == "NOT_REVERIFIED"
    assert inventory.entries[0].detail == "METADATA_ONLY_INTERACTIVE"


def test_streamlit_startup_uses_fast_paths_and_ops_keeps_deep_verification():
    app = (Path(__file__).resolve().parents[1] / "app.py").read_text(
        encoding="utf-8"
    )

    assert "deep_integrity=False" in app
    assert "inventory_backups_fast().as_dict()" in app
    assert "def _cached_deep_ops_readiness()" in app
    assert "deep_integrity=True" in app
    assert "inventory_backups().as_dict()" in app
