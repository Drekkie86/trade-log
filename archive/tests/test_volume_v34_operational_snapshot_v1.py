"""Test the exact one-time v34 production snapshot before attempting it live."""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import sys
import types

import pytest

import christiania_volume_v34_recovery_snapshot as rescue


def _fixture_db(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE schema_version(version INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO schema_version VALUES(34)")
        conn.execute("CREATE TABLE evidence(id INTEGER PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO evidence VALUES (1,'keep')")
        conn.commit()


def test_v34_snapshot_promotes_only_full_verified_copy(tmp_path, monkeypatch):
    source = tmp_path / "original.db"
    _fixture_db(source)
    volume = tmp_path / "volume"
    backup_dir = volume / "backups"
    backup_dir.mkdir(parents=True)
    monkeypatch.setattr(rescue, "STATUS", backup_dir / "status.json")
    monkeypatch.setattr(rescue, "require_storage", lambda **kw: 99 * 1024**3)
    fake_fcntl = types.ModuleType("fcntl")
    fake_fcntl.LOCK_EX = 2
    fake_fcntl.LOCK_NB = 4
    fake_fcntl.flock = lambda *_: None
    monkeypatch.setitem(sys.modules, "fcntl", fake_fcntl)
    result = rescue.take_snapshot(
        source=source, volume=volume, output_dir=backup_dir,
        expected_schema=34, prefix="christiania_backup", max_seconds=300,
    )
    assert result.is_file()
    assert result.name.startswith("christiania_backup_")
    assert json.loads((backup_dir / "status.json").read_text())["phase"] == "COMPLETE"
    manifest = json.loads(result.with_name(result.name + ".manifest.json").read_text())
    assert manifest["schema_version"] == 34
    assert manifest["verification_level"] == "routine"
    assert manifest["quick_check"] == "ok"
    assert manifest["integrity_check"] is None
    assert manifest["foreign_key_violation_count"] == 0
    assert manifest["snapshot_sha256"] == rescue.sha256(result)
    assert not list(backup_dir.glob("*.incomplete.db"))
    with sqlite3.connect(source) as con:
        assert con.execute("SELECT value FROM evidence").fetchone()[0] == "keep"
    with sqlite3.connect(result) as con:
        assert con.execute("SELECT value FROM evidence").fetchone()[0] == "keep"


def test_v34_snapshot_fails_closed_if_volume_not_mounted(tmp_path, monkeypatch):
    source = tmp_path / "source.db"
    _fixture_db(source)
    volume = tmp_path / "volume"
    target = volume / "backups"
    target.mkdir(parents=True)
    monkeypatch.setattr(Path, "is_mount", lambda self: False)
    with pytest.raises(RuntimeError, match="RECOVERY_VOLUME_NOT_INDEPENDENT_MOUNT"):
        rescue.require_storage(source=source, volume=volume, output_dir=target)
    assert not list(target.iterdir())


def test_v34_snapshot_fails_closed_before_wrong_schema_copy(tmp_path, monkeypatch):
    source = tmp_path / "original.db"
    _fixture_db(source)
    volume = tmp_path / "volume"
    backup_dir = volume / "backups"
    backup_dir.mkdir(parents=True)
    monkeypatch.setattr(rescue, "STATUS", backup_dir / "status.json")
    monkeypatch.setattr(rescue, "require_storage", lambda **kw: 99 * 1024**3)
    fake_fcntl = types.ModuleType("fcntl")
    fake_fcntl.LOCK_EX = 2
    fake_fcntl.LOCK_NB = 4
    fake_fcntl.flock = lambda *_: None
    monkeypatch.setitem(sys.modules, "fcntl", fake_fcntl)
    with pytest.raises(RuntimeError, match="WRONG_LIVE_SCHEMA"):
        rescue.take_snapshot(
            source=source, volume=volume, output_dir=backup_dir,
            expected_schema=36, prefix="christiania_backup", max_seconds=300,
        )
    assert not list(backup_dir.glob("*.db"))
    assert json.loads((backup_dir / "status.json").read_text())["phase"] == "FAILED"
