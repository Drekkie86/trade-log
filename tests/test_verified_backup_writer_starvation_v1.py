"""Regression: an active WAL heartbeat must not restart a full backup forever."""
from __future__ import annotations

from pathlib import Path
import sqlite3
import threading
import time

import pytest

from src.database.repository import EXPECTED_SCHEMA_VERSION
from src.operations import sqlite_runtime as runtime


def _live_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(
            "CREATE TABLE schema_version(version INTEGER PRIMARY KEY);"
            f"INSERT INTO schema_version VALUES({EXPECTED_SCHEMA_VERSION});"
            "CREATE TABLE heartbeat(seq INTEGER NOT NULL, mirror INTEGER NOT NULL);"
            "INSERT INTO heartbeat VALUES(0,0);"
            "CREATE TABLE payload(value BLOB NOT NULL);"
        )
        conn.execute("INSERT INTO payload VALUES(?)", (b"a" * (7 * 1024 * 1024),))
        conn.commit()
    finally:
        conn.close()


def test_vacuum_snapshot_remains_consistent_while_daemon_commits(tmp_path):
    source = tmp_path / "live.db"
    _live_db(source)
    stop = threading.Event()
    started = threading.Event()
    failures = []
    updates = []

    def heartbeat_writer() -> None:
        try:
            conn = sqlite3.connect(source, timeout=3.0)
            try:
                for seq in range(1, 200):
                    if stop.is_set():
                        break
                    conn.execute("UPDATE heartbeat SET seq=?, mirror=?", (seq, seq))
                    conn.commit()
                    updates.append(seq)
                    started.set()
                    time.sleep(0.005)
            finally:
                conn.close()
        except Exception as exc:
            failures.append(exc)
            started.set()

    worker = threading.Thread(target=heartbeat_writer)
    worker.start()
    assert started.wait(timeout=3), failures
    try:
        result = runtime.create_verified_backup(
            db_path=source, backup_dir=tmp_path / "backups", retention=2
        )
    finally:
        stop.set()
        worker.join(timeout=8)
    assert not worker.is_alive()
    assert not failures
    assert updates
    assert result.verification_level == "routine"
    assert result.quick_check == "ok"
    assert result.integrity_check is None
    assert result.foreign_key_violation_count == 0
    with sqlite3.connect(result.backup_path) as copy:
        seq, mirror = copy.execute(
            "SELECT seq,mirror FROM heartbeat"
        ).fetchone()
        assert seq == mirror
        assert 0 <= seq <= max(updates)
        assert copy.execute("SELECT length(value) FROM payload").fetchone()[0] == 7 * 1024 * 1024
    assert source.exists()
    assert not list((tmp_path / "backups").glob(".*tmp.db"))


def test_snapshot_hard_deadline_cleans_unverified_destination(tmp_path, monkeypatch):
    source = tmp_path / "live.db"
    _live_db(source)
    monkeypatch.setattr(runtime, "BACKUP_SNAPSHOT_TIMEOUT_SECONDS", 0)
    target = tmp_path / "backups"
    with pytest.raises(TimeoutError, match="SQLite snapshot exceeded"):
        runtime.create_verified_backup(
            db_path=source, backup_dir=target, retention=2
        )
    assert not list(target.glob("christiania_backup_*.db"))
    assert not list(target.glob(".*tmp.db"))
    assert source.exists()


def test_backup_unit_is_bounded_and_private():
    unit = (Path(__file__).resolve().parents[1] /
            "deploy/systemd/christiania-backup.service").read_text()
    assert "TimeoutStartSec=5400" in unit
    assert "UMask=0077" in unit


def test_snapshot_does_not_use_multistep_restartable_backup():
    import inspect
    source = inspect.getsource(runtime.create_verified_backup)
    helper = inspect.getsource(runtime._vacuum_into_snapshot)
    assert "source_conn.backup(" not in source
    assert "_vacuum_into_snapshot(" in source
    assert 'VACUUM main INTO ?' in helper
    assert 'mode=ro' in helper
