from __future__ import annotations

import os
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

from src.database.repository import EXPECTED_SCHEMA_VERSION
from src.operations.backup_compression import (
    compress_verified_backup,
    maintain_compressed_backups,
    manifest_path_for,
    verify_compressed_backup,
)
from src.operations.backup_recovery import (
    inventory_backups,
    run_restore_drill,
)
from src.operations.sqlite_runtime import create_verified_backup


def test_compressed_backup_roundtrip_is_verified(db_path, tmp_path):
    backup_dir = tmp_path / "backups"
    created = create_verified_backup(
        db_path=db_path,
        backup_dir=backup_dir,
        retention=3,
    )

    source = Path(created.backup_path)
    result = compress_verified_backup(source)

    compressed = Path(result.compressed_path)

    assert not source.exists()
    assert compressed.exists()
    assert manifest_path_for(compressed).is_file()
    assert result.schema_version == EXPECTED_SCHEMA_VERSION
    assert result.compressed_size_bytes > 0

    manifest = verify_compressed_backup(
        compressed,
        deep_payload=True,
    )

    assert manifest.schema_version == EXPECTED_SCHEMA_VERSION
    assert manifest.integrity_check == "ok"
    assert manifest.foreign_key_violation_count == 0

    drill = run_restore_drill(compressed)

    assert drill.state == "PASSED"
    assert drill.source_schema_version == EXPECTED_SCHEMA_VERSION
    assert drill.restored_schema_version == EXPECTED_SCHEMA_VERSION
    assert drill.integrity_check == "ok"
    assert drill.foreign_key_violation_count == 0


def test_maintenance_keeps_newest_backup_uncompressed(db_path, tmp_path):
    backup_dir = tmp_path / "backups"
    created = create_verified_backup(
        db_path=db_path,
        backup_dir=backup_dir,
        retention=5,
    )

    newest = Path(created.backup_path)
    older = backup_dir / "christiania_backup_20260101T000000Z.db"
    shutil.copy2(newest, older)

    now = datetime.now(UTC)
    old_time = (now - timedelta(days=1)).timestamp()
    new_time = now.timestamp()
    os.utime(older, (old_time, old_time))
    os.utime(newest, (new_time, new_time))

    result = maintain_compressed_backups(
        backup_dir,
        keep_latest_uncompressed=1,
    )

    assert result.compressed_count == 1
    assert newest.exists()
    assert not older.exists()
    compressed = Path(str(older) + ".gz")
    assert compressed.exists()
    assert manifest_path_for(compressed).exists()


def test_inventory_accepts_verified_mixed_plain_and_compressed_backups(
    db_path,
    tmp_path,
):
    backup_dir = tmp_path / "backups"
    created = create_verified_backup(
        db_path=db_path,
        backup_dir=backup_dir,
        retention=5,
    )

    newest = Path(created.backup_path)
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

    inventory = inventory_backups(
        backup_dir,
        now=now + timedelta(minutes=1),
    )

    assert inventory.total_files == 2
    assert inventory.valid_files == 2
    assert inventory.invalid_files == 0
    assert inventory.latest_valid_path == str(newest)
    details = {
        entry.filename: entry.detail
        for entry in inventory.entries
    }
    assert any(
        detail == "VERIFIED_COMPRESSED"
        for detail in details.values()
    )


def test_compressed_backup_corruption_is_rejected(db_path, tmp_path):
    import pytest

    backup_dir = tmp_path / "backups"
    created = create_verified_backup(
        db_path=db_path,
        backup_dir=backup_dir,
        retention=3,
    )
    compressed = Path(
        compress_verified_backup(
            created.backup_path
        ).compressed_path
    )

    payload = bytearray(compressed.read_bytes())
    payload[len(payload) // 2] ^= 0x01
    compressed.write_bytes(payload)

    with pytest.raises(
        RuntimeError,
        match="SHA-256",
    ):
        verify_compressed_backup(
            compressed,
            deep_payload=True,
        )
