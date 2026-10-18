"""Operational backup proof: real SQLite VACUUM, gzip SHA and separate restore.

Linux-only because production uses fcntl, systemd and independent volume.
No fixture is represented as historical/live profit or market data.
"""
from __future__ import annotations

import gzip
import hashlib
import importlib
import json
import sqlite3
import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="Production Linux-only sidecars")


def make_db(path):
    with sqlite3.connect(path) as con:
        con.execute("CREATE TABLE schema_version (version INTEGER)")
        con.execute("INSERT INTO schema_version VALUES (34)")
        for i in range(5):
            con.execute(f"CREATE TABLE fixture_{i} (id INTEGER PRIMARY KEY, blob TEXT)")
            con.executemany(f"INSERT INTO fixture_{i}(blob) VALUES (?)", [("X" * 800,) for _ in range(200)])
        con.commit()
    assert path.stat().st_size > 4096 * 100


def test_nightly_recovers_exact_data(tmp_path, monkeypatch):
    module = importlib.import_module("christiania_volume_backup_routine_20261018")
    root = tmp_path / "volume"
    backups = root / "backups"
    backups.mkdir(parents=True)
    live = tmp_path / "live.db"
    make_db(live)
    monkeypatch.setattr(module, "VOLUME", root)
    monkeypatch.setattr(module, "BACKUPS", backups)
    monkeypatch.setattr(module, "LIVE", live)
    monkeypatch.setattr(module, "STATUS", backups / "status.json")
    monkeypatch.setattr(module, "AUDIT_STATUS", backups / "audit.json")
    monkeypatch.setattr(module, "LOCK", backups / ".lock")
    module.run(fixture=True)
    module.audit_restore(fixture=True)
    assert json.loads((backups / "audit.json").read_text())["phase"] == "PASSED"
    archives = list(backups.glob("christiania_backup_*.db.gz"))
    assert len(archives) == 1
    archive = archives[0]
    manifest = json.loads((backups / (archive.name + ".manifest.json")).read_text())
    assert manifest["schema_version"] == 34
    assert manifest["verification_level"] == "archive_stream_sha256_crc_plus_real_restore_structural"
    assert manifest["full_sqlite_integrity_check"] is None
    assert manifest["restore_trial_completed"] is True
    assert hashlib.sha256(gzip.decompress(archive.read_bytes())).hexdigest() == manifest["source_sha256"]
    assert json.loads((backups / "status.json").read_text())["phase"] == "COMPLETE"
    assert not list(backups.glob(".christiania_trial_*.tmp.db"))
    assert not list(backups.glob(".christiania_backup_*.incomplete.db"))


def test_interrupted_snapshot_can_be_rescued_without_full_check(tmp_path, monkeypatch):
    module = importlib.import_module("christiania_finalize_v34_archive_20261018")
    backups = tmp_path / "backups"
    backups.mkdir()
    partial = backups / ".christiania_backup_20261017T203934Z.incomplete.db"
    make_db(partial)
    archive = backups / "christiania_backup_20261017T203934Z.db.gz"
    monkeypatch.setattr(module, "BACKUPS", backups)
    monkeypatch.setattr(module, "PARTIAL", partial)
    monkeypatch.setattr(module, "ARCHIVE", archive)
    monkeypatch.setattr(module, "MANIFEST", backups / (archive.name + ".manifest.json"))
    monkeypatch.setattr(module, "STATUS", backups / "status.json")
    monkeypatch.setattr(module, "LOCK", backups / ".lock")
    monkeypatch.setattr(module, "OLD_GZIP", backups / "prior_deep.db.gz")
    (backups / "prior_deep.db.gz").write_bytes(b"preserve")
    def fixture_preflight():
        return partial.stat(), module.structural_check(partial)
    monkeypatch.setattr(module, "preflight", fixture_preflight)
    module.finalize(release_source=True)
    manifest = json.loads((backups / (archive.name + ".manifest.json")).read_text())
    assert manifest["full_integrity_check"] is None
    assert manifest["verification_level"] == "archive_roundtrip_and_sqlite_structural"
    assert manifest["restore_trial_completed"]
    assert (backups / "prior_deep.db.gz").read_bytes() == b"preserve"
    assert not partial.exists()
