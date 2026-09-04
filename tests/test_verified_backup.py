import sqlite3
import time

from src.operations.sqlite_runtime import (
    create_verified_backup,
)


def _seed_source(path):
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "PRAGMA journal_mode=WAL;"
        )
        conn.execute(
            '''
            CREATE TABLE schema_version(
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            );
            '''
        )
        conn.execute(
            '''
            INSERT INTO schema_version(
                version,
                applied_at
            )
            VALUES(25, '2026-09-05T00:00:00Z');
            '''
        )
        conn.execute(
            '''
            CREATE TABLE evidence(
                id INTEGER PRIMARY KEY,
                value TEXT NOT NULL
            );
            '''
        )
        conn.execute(
            '''
            INSERT INTO evidence(value)
            VALUES('committed-wal-row');
            '''
        )
        conn.commit()
    finally:
        conn.close()


def test_verified_backup_preserves_committed_wal_data(
    tmp_path,
):
    source = tmp_path / "source.db"
    backup_dir = tmp_path / "backups"
    _seed_source(source)

    result = create_verified_backup(
        db_path=source,
        backup_dir=backup_dir,
        retention=3,
    )

    assert result.schema_version == 25
    assert result.integrity_check == "ok"
    assert (
        result.foreign_key_violation_count
        == 0
    )

    backup = sqlite3.connect(
        result.backup_path
    )

    try:
        value = backup.execute(
            '''
            SELECT value
            FROM evidence;
            '''
        ).fetchone()[0]

        assert value == "committed-wal-row"

    finally:
        backup.close()


def test_backup_retention_prunes_oldest(
    tmp_path,
):
    source = tmp_path / "source.db"
    backup_dir = tmp_path / "backups"
    _seed_source(source)
    backup_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    for index in range(3):
        stale = (
            backup_dir
            / f"christiania_backup_2026010{index + 1}T000000Z.db"
        )
        stale.write_bytes(
            b"stale"
        )
        old = 1_700_000_000 + index
        import os
        os.utime(stale, (old, old))

    result = create_verified_backup(
        db_path=source,
        backup_dir=backup_dir,
        retention=2,
    )

    backups = list(
        backup_dir.glob(
            "christiania_backup_*.db"
        )
    )

    assert len(backups) == 2
    assert result.pruned_count == 2

def test_verified_backup_rejects_stale_schema(
    tmp_path,
):
    source = tmp_path / "source.db"
    backup_dir = tmp_path / "backups"

    conn = sqlite3.connect(source)

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
            INSERT INTO schema_version(
                version,
                applied_at
            )
            VALUES(24, '2026-09-04T00:00:00Z');
            """
        )
        conn.commit()

    finally:
        conn.close()

    import pytest

    with pytest.raises(
        RuntimeError,
        match="does not match expected",
    ):
        create_verified_backup(
            db_path=source,
            backup_dir=backup_dir,
            retention=3,
        )

    assert not list(
        backup_dir.glob(
            "christiania_backup_*.db"
        )
    )
