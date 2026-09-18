from __future__ import annotations

import os
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from src.database.repository import EXPECTED_SCHEMA_VERSION
from src.operations.backup_recovery import (
    inventory_backups,
    resolve_latest_valid_backup,
    resolve_restore_drill_backup,
    run_restore_drill,
)
from src.operations.backup_compression import (
    compress_verified_backup,
    maintain_compressed_backups,
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
    assert drill.source_schema_version == EXPECTED_SCHEMA_VERSION
    assert drill.restored_schema_version == EXPECTED_SCHEMA_VERSION
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


def test_restore_drill_resolver_prefers_verified_compressed_backup(
    db_path,
    tmp_path,
):
    import shutil

    backup_dir = tmp_path / "backups"
    created = create_verified_backup(
        db_path=db_path,
        backup_dir=backup_dir,
        retention=5,
    )

    newest = os.path.abspath(created.backup_path)
    older = backup_dir / "christiania_backup_20260101T000000Z.db"
    shutil.copy2(newest, older)

    now = datetime.now(UTC)
    os.utime(
        older,
        (
            (now - timedelta(days=1)).timestamp(),
            (now - timedelta(days=1)).timestamp(),
        ),
    )
    os.utime(newest, (now.timestamp(), now.timestamp()))

    maintain_compressed_backups(
        backup_dir,
        keep_latest_uncompressed=1,
    )

    selected = resolve_restore_drill_backup(
        backup_dir
    )

    assert selected.name.endswith(".db.gz")
    drill = run_restore_drill(selected)
    assert drill.state == "PASSED"


def test_restore_drill_resolver_skips_historical_schema_compressed_backup(
    db_path,
    tmp_path,
):
    backup_dir = tmp_path / "backups"
    current = create_verified_backup(
        db_path=db_path,
        backup_dir=backup_dir,
        retention=5,
    )

    historical = backup_dir / "christiania_backup_20260101T000000Z.db"
    conn = sqlite3.connect(historical)
    try:
        conn.execute(
            """
            CREATE TABLE schema_version(
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            );
            """
        )
        conn.execute(
            """
            INSERT INTO schema_version(version, applied_at)
            VALUES(32, '2026-09-01T00:00:00Z');
            """
        )
        conn.execute(
            "CREATE TABLE evidence(id INTEGER PRIMARY KEY, value TEXT NOT NULL);"
        )
        conn.execute(
            "INSERT INTO evidence(value) VALUES('historical');"
        )
        conn.commit()
    finally:
        conn.close()

    historical_compressed = Path(
        compress_verified_backup(
            historical
        ).compressed_path
    )

    assert historical_compressed.exists()

    selected = resolve_restore_drill_backup(
        backup_dir
    )

    assert selected == Path(current.backup_path)
