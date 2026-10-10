"""Restore-drill safety/performance regressions after Oct 2026 timeouts.

These tests operate only on small, disposable SQLite fixture databases.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.database.repository import EXPECTED_SCHEMA_VERSION
from src.operations import backup_recovery as recovery
from src.operations.backup_compression import compress_verified_backup
from src.operations.sqlite_runtime import create_verified_backup


def _fresh_backup(db_path, tmp_path):
    return Path(create_verified_backup(
        db_path=db_path, backup_dir=tmp_path / "backups", retention=3
    ).backup_path)


def test_plain_selection_does_not_deep_validate_inventory(db_path, tmp_path, monkeypatch):
    path = _fresh_backup(db_path, tmp_path)

    def must_not_scan(_directory):
        raise AssertionError("Cannot inventory every large backup during selection")

    monkeypatch.setattr(recovery, "resolve_latest_valid_backup", must_not_scan)
    monkeypatch.setattr(recovery, "_inspect_sqlite", must_not_scan)
    assert recovery.resolve_restore_drill_backup(path.parent) == path


def test_plain_drill_verifies_restored_copy_once(db_path, tmp_path, monkeypatch):
    path = _fresh_backup(db_path, tmp_path)
    original = recovery._inspect_sqlite
    paths = []

    def inspect(p):
        paths.append(Path(p))
        return original(p)

    monkeypatch.setattr(recovery, "_inspect_sqlite", inspect)
    outcome = recovery.run_restore_drill(path)
    assert outcome.state == "PASSED"
    assert outcome.restored_schema_version == EXPECTED_SCHEMA_VERSION
    assert len(paths) == 1
    assert paths[0].name == "restored.db"
    assert paths[0] != path


def test_compressed_drill_does_not_repeat_already_verified_inspection(
    db_path, tmp_path, monkeypatch
):
    path = _fresh_backup(db_path, tmp_path)
    compressed = Path(compress_verified_backup(path).compressed_path)
    def unexpected_inspection(_path):
        raise AssertionError("Compressed restore already verified its restored DB")
    monkeypatch.setattr(recovery, "_inspect_sqlite", unexpected_inspection)
    assert recovery.run_restore_drill(compressed).state == "PASSED"


def test_insufficient_capacity_fails_before_heavy_restore(db_path, tmp_path, monkeypatch):
    path = _fresh_backup(db_path, tmp_path)
    source_bytes = path.stat().st_size
    gib = 1024 ** 3
    monkeypatch.setattr(
        recovery.shutil,
        "disk_usage",
        lambda _: SimpleNamespace(total=150 * gib, free=source_bytes + 15 * gib - 1),
    )
    with pytest.raises(RuntimeError, match="INSUFFICIENT_SCRATCH_HEADROOM"):
        recovery.run_restore_drill(path)


def test_invalid_latest_metadata_does_not_hide_valid_backup(db_path, tmp_path):
    original = _fresh_backup(db_path, tmp_path)
    bad = original.parent / "christiania_backup_20990101T000000Z.db"
    bad.write_bytes(b"not sqlite")
    assert recovery.resolve_restore_drill_backup(original.parent) == original
