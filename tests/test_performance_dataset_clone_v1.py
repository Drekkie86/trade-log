"""Pre-migration performance probes must not upgrade the live database."""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3

import pytest

from src.operations import probe_dataset_clone as clone


def sample_source(tmp_path):
    source = tmp_path / "production.db"
    with sqlite3.connect(source) as conn:
        conn.execute("CREATE TABLE schema_version(version INTEGER NOT NULL)")
        conn.execute("INSERT INTO schema_version VALUES (34)")
        conn.execute("CREATE TABLE live_evidence(id INTEGER PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO live_evidence VALUES (1, 'immutable')")
        conn.commit()
    return source


def migrations(tmp_path):
    directory = tmp_path / "migrations"
    directory.mkdir()
    (directory / "035_probe.sql").write_text(
        "CREATE TABLE probe_addition_35(id INTEGER PRIMARY KEY);\n"
        "INSERT INTO schema_version VALUES (35);\n",
        encoding="utf-8"
    )
    (directory / "036_probe.sql").write_text(
        "CREATE TABLE probe_addition_36(id INTEGER PRIMARY KEY);\n"
        "INSERT INTO schema_version VALUES (36);\n",
        encoding="utf-8"
    )
    (directory / "037_probe.sql").write_text(
        "CREATE TABLE probe_addition_37(id INTEGER PRIMARY KEY);\n"
        "INSERT INTO schema_version VALUES (37);\n",
        encoding="utf-8"
    )
    (directory / "038_probe.sql").write_text(
        "CREATE TABLE probe_addition_38(id INTEGER PRIMARY KEY);\n"
        "INSERT INTO schema_version VALUES (38);\n",
        encoding="utf-8"
    )
    return directory


def test_pre_release_probe_migrates_only_disposable_volume_copy(tmp_path, monkeypatch):
    source = sample_source(tmp_path)
    before = source.read_bytes()
    volume = tmp_path / "recovery-volume"
    scratch = volume / "scratch" / "isolated-probe"
    scratch.mkdir(parents=True)
    target = scratch / "probe.db"
    provenance = scratch / "provenance.json"
    monkeypatch.setattr(clone, "_mounted_volume_is_separate", lambda *_: True)
    monkeypatch.setattr(clone, "RESERVE_MIN_BYTES", 1)
    monkeypatch.setattr(clone, "RESERVE_FRACTION", 0.0)

    result = clone.prepare_probe_dataset(
        source=source, target=target, provenance=provenance,
        migrations_dir=migrations(tmp_path), volume=volume,
    )
    assert result == target
    assert source.read_bytes() == before
    with sqlite3.connect(source) as conn:
        assert conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] == 34
    with sqlite3.connect(target) as conn:
        assert conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] == 38
        assert conn.execute("SELECT value FROM live_evidence").fetchone()[0] == "immutable"
        assert conn.execute("SELECT count(*) FROM sqlite_master WHERE name='probe_addition_36'").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM sqlite_master WHERE name='probe_addition_37'").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM sqlite_master WHERE name='probe_addition_38'").fetchone()[0] == 1
    proof = json.loads(provenance.read_text())
    assert proof["kind"] == "disposable_live_sqlite_snapshot"
    assert proof["source_schema_version"] == 34
    assert proof["measured_schema_version"] == 38
    assert proof["disposable_migration"] is True


def test_missing_recovery_mount_blocks_copy(tmp_path, monkeypatch):
    source = sample_source(tmp_path)
    volume = tmp_path / "missing-volume"
    scratch = volume / "scratch" / "run"
    scratch.mkdir(parents=True)
    monkeypatch.setattr(clone, "_mounted_volume_is_separate", lambda *_: False)
    with pytest.raises(RuntimeError, match="VOLUME_NOT_SEPARATELY_MOUNTED"):
        clone.prepare_probe_dataset(
            source=source, target=scratch / "probe.db",
            provenance=scratch / "proof.json", migrations_dir=migrations(tmp_path),
            volume=volume,
        )
    assert list(scratch.iterdir()) == []


def test_preexisting_destination_refuses_overwrite(tmp_path, monkeypatch):
    source = sample_source(tmp_path)
    volume = tmp_path / "volume"
    scratch = volume / "scratch" / "run"
    scratch.mkdir(parents=True)
    target = scratch / "probe.db"
    target.write_bytes(b"important")
    monkeypatch.setattr(clone, "_mounted_volume_is_separate", lambda *_: True)
    with pytest.raises(RuntimeError, match="TARGET_EXISTS"):
        clone.prepare_probe_dataset(
            source=source, target=target,
            provenance=scratch / "proof.json", migrations_dir=migrations(tmp_path),
            volume=volume,
        )
    assert target.read_bytes() == b"important"


def test_probe_clone_completes_with_concurrent_wal_updates(tmp_path, monkeypatch):
    """Daemon-like updates must not restart the scratch snapshot."""
    from threading import Event, Thread

    source = sample_source(tmp_path)
    with sqlite3.connect(source) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.commit()

    volume = tmp_path / "recovery-volume"
    scratch = volume / "scratch" / "wal-probe"
    scratch.mkdir(parents=True)
    monkeypatch.setattr(clone, "_mounted_volume_is_separate", lambda *_: True)
    monkeypatch.setattr(clone, "RESERVE_MIN_BYTES", 1)
    monkeypatch.setattr(clone, "RESERVE_FRACTION", 0.0)
    stopped = Event()
    started = Event()
    failures: list[Exception] = []

    def write_daemon_updates() -> None:
        try:
            with sqlite3.connect(source, timeout=5) as conn:
                while not stopped.is_set():
                    conn.execute(
                        "UPDATE live_evidence SET value='updated' WHERE id=1"
                    )
                    conn.commit()
                    started.set()
                    stopped.wait(0.005)
        except Exception as exc:
            failures.append(exc)
            started.set()

    writer = Thread(target=write_daemon_updates, daemon=True)
    writer.start()
    try:
        assert started.wait(timeout=5)
        assert not failures
        result = clone.prepare_probe_dataset(
            source=source,
            target=scratch / "probe.db",
            provenance=scratch / "provenance.json",
            migrations_dir=migrations(tmp_path),
            volume=volume,
        )
    finally:
        stopped.set()
        writer.join(timeout=5)

    assert not writer.is_alive()
    assert not failures
    with sqlite3.connect(result) as db:
        assert db.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] == clone.EXPECTED_SCHEMA_VERSION
        assert db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
