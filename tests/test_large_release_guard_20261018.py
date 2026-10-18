"""Large additive release must remain lossless and fail closed without recovery proof."""
from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import christiania_release_database as rd
from src.database.migration_runner import apply_pending_migrations, get_schema_version
from src.database.repository import EXPECTED_SCHEMA_VERSION
from src.operations import large_release_guard as lg
from src.operations.sqlite_runtime import inspect_database

ROOT=Path(__file__).resolve().parents[1]


def _v34(tmp_path):
    migrations=tmp_path/"to_v34"
    migrations.mkdir()
    for m in (ROOT/"migrations").glob("*.sql"):
        if int(m.name.split("_",1)[0])<=34:
            shutil.copy2(m,migrations/m.name)
    path=tmp_path/"source.db"
    with sqlite3.connect(path) as c:
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript((ROOT/"trade_log_schema.sql").read_text(encoding="utf-8"))
        apply_pending_migrations(c,migrations)
        assert get_schema_version(c)==34
    return path


def test_real_v34_to_current_bounded_additive_release_still_restorable(tmp_path,monkeypatch):
    db=_v34(tmp_path)
    backup_dir=tmp_path/"backups"
    monkeypatch.setenv("CHRISTIANIA_DB_PATH",str(db))
    monkeypatch.setenv("CHRISTIANIA_BACKUP_DIR",str(backup_dir))
    monkeypatch.setattr(rd,"LARGE_DB_THRESHOLD_BYTES",0)
    audit=lambda **_kw: {"restored_bytes":123,"schema_version":34}
    monkeypatch.setattr(rd,"require_recent_independent_restored_archive",audit)
    monkeypatch.setattr(lg,"require_recent_independent_restored_archive",audit)
    pointer=tmp_path/"pointer.txt"
    result=rd.prepare_release_database(
        migrations_dir=ROOT/"migrations",rollback_pointer=pointer
    )
    assert result.schema_before==34
    assert result.schema_after==EXPECTED_SCHEMA_VERSION
    assert Path(result.backup_path).is_file()
    assert pointer.is_file() and "34\t" in pointer.read_text()
    full=inspect_database(db)
    assert full.quick_check=="ok" and full.foreign_key_violation_count==0
    assert result.migrated
    assert rd.restore_backup(
        database=db,backup=Path(result.backup_path),expected_version=34
    )==34
    assert inspect_database(db).quick_check=="ok"


def test_large_release_refuses_unverified_independent_recovery_before_copy(tmp_path,monkeypatch):
    db=_v34(tmp_path)
    backup_dir=tmp_path/"backups"
    backup_dir.mkdir()
    monkeypatch.setenv("CHRISTIANIA_DB_PATH",str(db))
    monkeypatch.setenv("CHRISTIANIA_BACKUP_DIR",str(backup_dir))
    monkeypatch.setattr(rd,"LARGE_DB_THRESHOLD_BYTES",0)
    with pytest.raises(RuntimeError,match="INDEPENDENT_VOLUME"):
        rd.prepare_release_database(migrations_dir=ROOT/"migrations")
    assert not list(backup_dir.glob("christiania_release_rollback_*"))
    assert inspect_database(db).schema_version==34


def test_backup_identity_verification_detects_changed_high_watermarks(tmp_path,monkeypatch):
    source=tmp_path/"source.db"
    target=tmp_path/"copy.db"
    with sqlite3.connect(source) as c:
        c.execute("CREATE TABLE schema_version(version INTEGER)")
        c.execute("INSERT INTO schema_version VALUES (34)")
        c.execute("CREATE TABLE research_runs(id INTEGER PRIMARY KEY)")
        c.execute("INSERT INTO research_runs VALUES (17)")
        c.commit()
        target_connection=sqlite3.connect(target)
        try:
            c.backup(target_connection)
        finally:
            target_connection.close()
    monkeypatch.setattr(lg,"require_recent_independent_restored_archive",
                        lambda **_kw:{"restored_bytes":42})
    assert lg.verify_sqlite_backup_bounded(
        source=source,copy=target,expected_version=34,recovery_dir=tmp_path
    )["schema"]==34
    with sqlite3.connect(target) as c:
        c.execute("INSERT INTO research_runs VALUES (18)")
    with pytest.raises(RuntimeError,match="METADATA_OR_HIGHWATER"):
        lg.verify_sqlite_backup_bounded(
            source=source,copy=target,expected_version=34,recovery_dir=tmp_path
        )


def test_fresh_external_restore_rejects_unverified_same_volume(tmp_path):
    live=tmp_path/"source.db"
    live.write_bytes(b"SQLite")
    with pytest.raises(RuntimeError,match="INDEPENDENT_VOLUME"):
        lg.require_recent_independent_restored_archive(
            source=live,backup_dir=tmp_path,expected_schema_version=34,
        )
