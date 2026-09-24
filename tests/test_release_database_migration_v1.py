from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

import christiania_release_database as release_db
from christiania_release_database import (
    prepare_release_database,
    restore_backup,
)
from src.database.migration_runner import apply_pending_migrations, get_schema_version
from src.database.repository import EXPECTED_SCHEMA_VERSION
from src.operations.sqlite_runtime import inspect_database


ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "migrations"
SCHEMA = ROOT / "trade_log_schema.sql"


def _make_v27_database(tmp_path: Path) -> Path:
    db = tmp_path / "release_v27.db"
    migrations_v27 = tmp_path / "migrations_v27"
    migrations_v27.mkdir()

    for migration in MIGRATIONS.glob("*.sql"):
        version = int(migration.name.split("_", 1)[0])
        if version <= 27:
            shutil.copy2(migration, migrations_v27 / migration.name)

    conn = sqlite3.connect(db)
    try:
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.executescript(SCHEMA.read_text(encoding="utf-8"))
        apply_pending_migrations(conn, migrations_v27)
        conn.commit()
        assert get_schema_version(conn) == 27
    finally:
        conn.close()

    return db


def test_release_database_prepares_v27_to_current_and_can_restore(
    monkeypatch,
    tmp_path,
):
    db = _make_v27_database(tmp_path)
    backups = tmp_path / "backups"
    pointer = tmp_path / "rollback-pointer.txt"

    monkeypatch.setenv("CHRISTIANIA_DB_PATH", str(db))
    monkeypatch.setenv("CHRISTIANIA_BACKUP_DIR", str(backups))

    result = prepare_release_database(
        migrations_dir=MIGRATIONS,
        rollback_pointer=pointer,
    )

    assert result.schema_before == 27
    assert result.schema_after == EXPECTED_SCHEMA_VERSION
    assert result.migrated is True
    assert Path(result.backup_path).is_file()
    assert pointer.read_text(encoding="utf-8") == (
        f"27\t{result.backup_path}\n"
    )

    migrated = inspect_database(db)
    assert migrated.schema_version == EXPECTED_SCHEMA_VERSION
    assert migrated.journal_mode == "wal"
    assert migrated.quick_check == "ok"
    assert migrated.foreign_key_violation_count == 0

    restored_version = restore_backup(
        database=db,
        backup=Path(result.backup_path),
        expected_version=27,
    )
    assert restored_version == 27

    restored = inspect_database(db)
    assert restored.schema_version == 27
    assert restored.journal_mode == "wal"
    assert restored.quick_check == "ok"
    assert restored.foreign_key_violation_count == 0


def test_failed_release_migration_restores_pre_release_database(
    monkeypatch,
    tmp_path,
):
    db = _make_v27_database(tmp_path)
    backups = tmp_path / "backups"
    bad_migrations = tmp_path / "bad_migrations"
    bad_migrations.mkdir()

    bad_028 = bad_migrations / "028_broken.sql"
    bad_028.write_text(
        "CREATE TABLE release_migration_probe (id INTEGER);\n"
        "THIS IS NOT VALID SQL;\n"
        "INSERT INTO schema_version(version) VALUES (28);\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("CHRISTIANIA_DB_PATH", str(db))
    monkeypatch.setenv("CHRISTIANIA_BACKUP_DIR", str(backups))

    with pytest.raises(sqlite3.Error):
        prepare_release_database(
            migrations_dir=bad_migrations,
        )

    health = inspect_database(db)
    assert health.schema_version == 27
    assert health.journal_mode == "wal"
    assert health.quick_check == "ok"
    assert health.foreign_key_violation_count == 0

    conn = sqlite3.connect(db)
    try:
        probe = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='release_migration_probe';"
        ).fetchone()
    finally:
        conn.close()

    assert probe is None


def test_rollback_pointer_is_committed_before_migration_sql(
    monkeypatch,
    tmp_path,
):
    db = _make_v27_database(tmp_path)
    backups = tmp_path / "backups"
    pointer = tmp_path / "rollback-pointer.txt"

    monkeypatch.setenv("CHRISTIANIA_DB_PATH", str(db))
    monkeypatch.setenv("CHRISTIANIA_BACKUP_DIR", str(backups))

    original = release_db.apply_pending_migrations

    def guarded_apply(conn, migrations_dir):
        assert pointer.is_file()
        text = pointer.read_text(encoding="utf-8")
        version, backup_path = text.rstrip("\n").split("\t", 1)
        assert version == "27"
        assert Path(backup_path).is_file()
        return original(conn, migrations_dir)

    monkeypatch.setattr(release_db, "apply_pending_migrations", guarded_apply)

    result = prepare_release_database(
        migrations_dir=MIGRATIONS,
        rollback_pointer=pointer,
    )
    assert result.schema_after == EXPECTED_SCHEMA_VERSION


def test_rollback_directory_entries_are_synced_before_migration_sql(
    monkeypatch,
    tmp_path,
):
    db = _make_v27_database(tmp_path)
    backups = tmp_path / "backups"
    pointer = tmp_path / "rollback-pointer.txt"

    monkeypatch.setenv("CHRISTIANIA_DB_PATH", str(db))
    monkeypatch.setenv("CHRISTIANIA_BACKUP_DIR", str(backups))

    synced_directories: list[Path] = []
    original = release_db.apply_pending_migrations

    def record_fsync(path):
        synced_directories.append(Path(path))

    def guarded_apply(conn, migrations_dir):
        assert backups in synced_directories
        assert pointer.parent in synced_directories
        return original(conn, migrations_dir)

    monkeypatch.setattr(release_db, "_fsync_directory", record_fsync)
    monkeypatch.setattr(release_db, "apply_pending_migrations", guarded_apply)

    result = prepare_release_database(
        migrations_dir=MIGRATIONS,
        rollback_pointer=pointer,
    )
    assert result.schema_after == EXPECTED_SCHEMA_VERSION


def test_keyboard_interrupt_during_migration_restores_v27(
    monkeypatch,
    tmp_path,
):
    db = _make_v27_database(tmp_path)
    backups = tmp_path / "backups"
    pointer = tmp_path / "rollback-pointer.txt"

    monkeypatch.setenv("CHRISTIANIA_DB_PATH", str(db))
    monkeypatch.setenv("CHRISTIANIA_BACKUP_DIR", str(backups))

    def interrupted_apply(conn, migrations_dir):
        del migrations_dir
        conn.execute("CREATE TABLE interrupted_release_probe (id INTEGER);")
        conn.commit()
        raise KeyboardInterrupt()

    monkeypatch.setattr(release_db, "apply_pending_migrations", interrupted_apply)

    with pytest.raises(KeyboardInterrupt):
        prepare_release_database(
            migrations_dir=MIGRATIONS,
            rollback_pointer=pointer,
        )

    version, backup_path = pointer.read_text(encoding="utf-8").rstrip("\n").split("\t", 1)
    assert version == "27"
    assert Path(backup_path).is_file()

    health = inspect_database(db)
    assert health.schema_version == 27
    assert health.journal_mode == "wal"
    assert health.quick_check == "ok"
    assert health.foreign_key_violation_count == 0

    conn = sqlite3.connect(db)
    try:
        probe = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='interrupted_release_probe';"
        ).fetchone()
    finally:
        conn.close()
    assert probe is None



def test_release_migration_capacity_fails_before_rollback_copy(
    monkeypatch,
    tmp_path,
):
    db = _make_v27_database(
        tmp_path
    )
    backups = (
        tmp_path
        / "backups"
    )

    monkeypatch.setenv(
        "CHRISTIANIA_DB_PATH",
        str(db),
    )
    monkeypatch.setenv(
        "CHRISTIANIA_BACKUP_DIR",
        str(backups),
    )

    copied = False

    def fail_capacity(
        database,
        backup_dir,
    ):
        del database, backup_dir
        raise RuntimeError(
            "capacity-test"
        )

    def forbidden_copy(
        database,
        backup_dir,
        *,
        schema_version,
    ):
        nonlocal copied
        del database, backup_dir, schema_version
        copied = True
        raise AssertionError(
            "rollback copy must not start"
        )

    monkeypatch.setattr(
        release_db,
        "_assert_release_migration_capacity",
        fail_capacity,
    )
    monkeypatch.setattr(
        release_db,
        "_create_rollback_backup",
        forbidden_copy,
    )

    with pytest.raises(
        RuntimeError,
        match="capacity-test",
    ):
        prepare_release_database(
            migrations_dir=MIGRATIONS,
        )

    assert copied is False
    assert not list(
        backups.glob(
            "christiania_release_rollback_*.db"
        )
    )


def test_release_migration_capacity_same_filesystem_accounts_for_all_headroom(
    monkeypatch,
    tmp_path,
):
    db = tmp_path / "db.sqlite"
    db.write_bytes(
        b"x"
    )
    backups = (
        tmp_path
        / "backups"
    )
    backups.mkdir()

    monkeypatch.setattr(
        release_db,
        "backup_logical_source_bytes",
        lambda source: 1_000,
    )
    monkeypatch.setattr(
        release_db,
        "backup_required_free_bytes",
        lambda *,
        source_size_bytes,
        filesystem_total_bytes: (
            source_size_bytes
            + 500
        ),
    )
    monkeypatch.setattr(
        release_db,
        "_release_migration_extra_headroom_bytes",
        lambda logical: 200,
    )
    monkeypatch.setattr(
        release_db.os,
        "stat",
        lambda path: SimpleNamespace(
            st_dev=7
        ),
    )

    monkeypatch.setattr(
        release_db.shutil,
        "disk_usage",
        lambda path: SimpleNamespace(
            total=10_000,
            used=8_400,
            free=1_600,
        ),
    )

    with pytest.raises(
        RuntimeError,
        match=(
            "Insufficient release-migration "
            "filesystem headroom"
        ),
    ):
        release_db._assert_release_migration_capacity(
            db,
            backups,
        )

    monkeypatch.setattr(
        release_db.shutil,
        "disk_usage",
        lambda path: SimpleNamespace(
            total=10_000,
            used=8_200,
            free=1_800,
        ),
    )

    result = (
        release_db._assert_release_migration_capacity(
            db,
            backups,
        )
    )

    assert (
        result[
            "same_filesystem"
        ]
        is True
    )
    assert (
        result[
            "required_database_free_bytes"
        ]
        == 1_700
    )
    assert (
        result[
            "required_backup_free_bytes"
        ]
        == 1_700
    )
