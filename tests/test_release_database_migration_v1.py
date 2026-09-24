from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

import christiania_release_database as release_db
from christiania_release_database import (
    preflight_release_database,
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



def test_release_migration_capacity_preflight_runs_before_rollback_copy(
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
    pointer = (
        tmp_path
        / "rollback-pointer.txt"
    )

    monkeypatch.setenv(
        "CHRISTIANIA_DB_PATH",
        str(db),
    )
    monkeypatch.setenv(
        "CHRISTIANIA_BACKUP_DIR",
        str(backups),
    )

    observed = []
    original_copy = (
        release_db._copy_sqlite_backup
    )

    def capacity(
        *,
        source,
        target_dir,
    ):
        observed.append(
            (
                "capacity",
                Path(source),
                Path(target_dir),
            )
        )

    def copy(
        database,
        temp_path,
    ):
        assert observed
        assert (
            observed[0][0]
            == "capacity"
        )
        observed.append(
            (
                "copy",
                Path(database),
                Path(temp_path),
            )
        )
        return original_copy(
            database,
            temp_path,
        )

    monkeypatch.setattr(
        release_db,
        "assert_backup_capacity",
        capacity,
    )
    monkeypatch.setattr(
        release_db,
        "_copy_sqlite_backup",
        copy,
    )

    result = (
        prepare_release_database(
            migrations_dir=MIGRATIONS,
            rollback_pointer=pointer,
        )
    )

    assert (
        result.schema_after
        == EXPECTED_SCHEMA_VERSION
    )
    assert (
        observed[0][0]
        == "capacity"
    )
    assert (
        observed[1][0]
        == "copy"
    )


def test_release_migration_capacity_failure_creates_no_rollback_artifact(
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
    pointer = (
        tmp_path
        / "rollback-pointer.txt"
    )

    monkeypatch.setenv(
        "CHRISTIANIA_DB_PATH",
        str(db),
    )
    monkeypatch.setenv(
        "CHRISTIANIA_BACKUP_DIR",
        str(backups),
    )

    def reject_capacity(
        *,
        source,
        target_dir,
    ):
        del source
        del target_dir
        raise RuntimeError(
            "synthetic insufficient headroom"
        )

    copy_called = False

    def unexpected_copy(
        database,
        temp_path,
    ):
        nonlocal copy_called
        del database
        del temp_path
        copy_called = True
        raise AssertionError(
            "copy must not run after "
            "capacity failure"
        )

    monkeypatch.setattr(
        release_db,
        "assert_backup_capacity",
        reject_capacity,
    )
    monkeypatch.setattr(
        release_db,
        "_copy_sqlite_backup",
        unexpected_copy,
    )

    with pytest.raises(
        RuntimeError,
        match="synthetic insufficient headroom",
    ):
        prepare_release_database(
            migrations_dir=MIGRATIONS,
            rollback_pointer=pointer,
        )

    assert copy_called is False
    assert pointer.exists() is False

    if backups.exists():
        assert list(
            backups.iterdir()
        ) == []

    assert (
        inspect_database(
            db
        ).schema_version
        == 27
    )


def test_release_rollback_copy_failure_removes_partial_temp_file(
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
    pointer = (
        tmp_path
        / "rollback-pointer.txt"
    )

    monkeypatch.setenv(
        "CHRISTIANIA_DB_PATH",
        str(db),
    )
    monkeypatch.setenv(
        "CHRISTIANIA_BACKUP_DIR",
        str(backups),
    )

    monkeypatch.setattr(
        release_db,
        "assert_backup_capacity",
        lambda **kwargs: None,
    )

    def failed_copy(
        database,
        temp_path,
    ):
        del database

        Path(
            temp_path
        ).write_bytes(
            b"partial rollback copy"
        )

        raise RuntimeError(
            "synthetic backup copy failure"
        )

    monkeypatch.setattr(
        release_db,
        "_copy_sqlite_backup",
        failed_copy,
    )

    with pytest.raises(
        RuntimeError,
        match="synthetic backup copy failure",
    ):
        prepare_release_database(
            migrations_dir=MIGRATIONS,
            rollback_pointer=pointer,
        )

    assert pointer.exists() is False

    assert list(
        backups.glob(
            "*.tmp.db"
        )
    ) == []

    assert list(
        backups.glob(
            "christiania_release_rollback_*.db"
        )
    ) == []

    assert (
        inspect_database(
            db
        ).schema_version
        == 27
    )



def test_release_database_preflight_surfaces_migration_capacity(
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

    monkeypatch.setattr(
        release_db,
        "backup_logical_source_bytes",
        lambda source: 100,
    )
    monkeypatch.setattr(
        release_db.shutil,
        "disk_usage",
        lambda path: type(
            "Usage",
            (),
            {
                "total": 1000,
                "free": 900,
            },
        )(),
    )
    monkeypatch.setattr(
        release_db,
        "backup_required_free_bytes",
        lambda **kwargs: 500,
    )
    monkeypatch.setattr(
        release_db,
        "_migration_storage_headroom_bytes",
        lambda *args, **kwargs: 200,
    )

    result = (
        preflight_release_database()
    )

    assert result.passed is True
    assert result.migration_required is True
    assert result.schema_before == 27
    assert (
        result.schema_target
        == EXPECTED_SCHEMA_VERSION
    )
    assert (
        result.logical_source_bytes
        == 100
    )
    assert (
        result.filesystem_free_bytes
        == 900
    )
    assert (
        result.backup_and_reserve_bytes
        == 500
    )
    assert (
        result.migration_storage_headroom_bytes
        == 200
    )
    assert (
        result.required_free_bytes
        == 700
    )
    assert (
        result.capacity_state
        == "PASS"
    )


def test_release_database_preflight_fails_capacity_without_mutating_database(
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

    monkeypatch.setattr(
        release_db,
        "backup_logical_source_bytes",
        lambda source: 700,
    )
    monkeypatch.setattr(
        release_db.shutil,
        "disk_usage",
        lambda path: type(
            "Usage",
            (),
            {
                "total": 1000,
                "free": 400,
            },
        )(),
    )
    monkeypatch.setattr(
        release_db,
        "backup_required_free_bytes",
        lambda **kwargs: 500,
    )
    monkeypatch.setattr(
        release_db,
        "_migration_storage_headroom_bytes",
        lambda *args, **kwargs: 200,
    )

    result = (
        preflight_release_database()
    )

    assert result.passed is False
    assert (
        result.capacity_state
        == "FAIL"
    )
    assert (
        result.filesystem_free_bytes
        == 400
    )
    assert (
        result.backup_and_reserve_bytes
        == 500
    )
    assert (
        result.migration_storage_headroom_bytes
        == 200
    )
    assert (
        result.required_free_bytes
        == 700
    )

    assert (
        inspect_database(
            db
        ).schema_version
        == 27
    )

    assert list(
        backups.glob(
            "christiania_release_rollback_*"
        )
    ) == []



def test_v34_migration_headroom_uses_reviewed_same_table_index_proxies(
    tmp_path,
):
    db = _make_v27_database(
        tmp_path
    )

    conn = sqlite3.connect(
        db
    )
    try:
        rows = conn.execute(
            """
            SELECT
                name,
                SUM(pgsize)
            FROM dbstat
            WHERE name IN (
                'idx_shadow_candidates_run',
                'uq_hypothesis_scanner_evaluation_quote',
                'idx_surface_v2_quote'
            )
            GROUP BY name;
            """
        ).fetchall()
    finally:
        conn.close()

    sizes = {
        str(name): int(
            value
        )
        for name, value
        in rows
    }

    assert set(
        sizes
    ) == {
        "idx_shadow_candidates_run",
        "uq_hypothesis_scanner_evaluation_quote",
        "idx_surface_v2_quote",
    }

    final_index_upper_bound = (
        sizes[
            "idx_shadow_candidates_run"
        ]
        * 3
        + sizes[
            "uq_hypothesis_scanner_evaluation_quote"
        ]
        * 2
        + sizes[
            "idx_surface_v2_quote"
        ]
    )

    observed = (
        release_db._migration_storage_headroom_bytes(
            db,
            schema_before=27,
            schema_target=34,
        )
    )

    assert (
        observed
        == final_index_upper_bound
        * 2
    )


def test_v34_migration_headroom_fails_closed_without_dbstat_proxy(
    monkeypatch,
    tmp_path,
):
    db = _make_v27_database(
        tmp_path
    )

    original = (
        release_db._sqlite_object_bytes
    )

    def missing_proxy(
        database,
        names,
    ):
        values = original(
            database,
            names,
        )
        values.pop(
            "idx_surface_v2_quote"
        )
        missing = [
            name
            for name
            in names
            if values.get(
                name,
                0,
            )
            <= 0
        ]
        if missing:
            raise RuntimeError(
                "synthetic missing proxy: "
                + ",".join(
                    missing
                )
            )
        return values

    monkeypatch.setattr(
        release_db,
        "_sqlite_object_bytes",
        missing_proxy,
    )

    with pytest.raises(
        RuntimeError,
        match="synthetic missing proxy",
    ):
        release_db._migration_storage_headroom_bytes(
            db,
            schema_before=27,
            schema_target=34,
        )
