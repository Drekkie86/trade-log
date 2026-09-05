from __future__ import annotations

import os
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from src.operations.backup_recovery import (
    inventory_backups,
    resolve_latest_valid_backup,
    run_restore_drill,
)
from src.operations.sqlite_runtime import create_verified_backup


def test_backup_inventory_verifies_and_selects_latest(db_path, tmp_path):
    backup_dir = tmp_path / "backups"
    first = create_verified_backup(db_path=db_path, backup_dir=backup_dir, retention=5)
    first_path = backup_dir / first.backup_path.split(os.sep)[-1]
    old = datetime.now(UTC) - timedelta(hours=10)
    os.utime(first_path, (old.timestamp(), old.timestamp()))

    renamed = backup_dir / "christiania_backup_20990101T000000Z.db"
    first_path.replace(renamed)
    newer = datetime.now(UTC) - timedelta(hours=1)
    os.utime(renamed, (newer.timestamp(), newer.timestamp()))

    inventory = inventory_backups(backup_dir, now=datetime.now(UTC))
    assert inventory.valid_files == 1
    assert inventory.invalid_files == 0
    assert inventory.latest_valid_path == str(renamed)
    assert inventory.latest_valid_age_hours is not None
    assert inventory.latest_valid_age_hours < 2


def test_backup_inventory_marks_corrupt_file_invalid(tmp_path):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    corrupt = backup_dir / "christiania_backup_20260905T000000Z.db"
    corrupt.write_bytes(b"not sqlite")

    inventory = inventory_backups(backup_dir)
    assert inventory.total_files == 1
    assert inventory.valid_files == 0
    assert inventory.invalid_files == 1
    assert inventory.entries[0].state == "INVALID"


def test_restore_drill_never_changes_source_backup(db_path, tmp_path):
    backup_dir = tmp_path / "backups"
    result = create_verified_backup(db_path=db_path, backup_dir=backup_dir, retention=3)
    backup = result.backup_path
    before = open(backup, "rb").read()

    drill = run_restore_drill(backup)

    after = open(backup, "rb").read()
    assert drill.state == "PASSED"
    assert drill.source_schema_version == 25
    assert drill.restored_schema_version == 25
    assert drill.integrity_check == "ok"
    assert drill.foreign_key_violation_count == 0
    assert before == after


def test_restore_drill_rejects_invalid_backup(tmp_path):
    bad = tmp_path / "bad.db"
    bad.write_bytes(b"bad")
    with pytest.raises(RuntimeError, match="not valid"):
        run_restore_drill(bad)


def test_latest_valid_backup_refuses_empty_directory(tmp_path):
    with pytest.raises(FileNotFoundError):
        resolve_latest_valid_backup(tmp_path / "empty")
