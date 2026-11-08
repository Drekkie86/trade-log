from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import sys
import types

import pytest

import christiania_resume_v34_snapshot_20261018 as resume
import christiania_volume_v34_recovery_snapshot as bridge


@pytest.fixture
def recovery(tmp_path, monkeypatch):
    root = tmp_path / "volume"
    backups = root / "backups"
    backups.mkdir(parents=True)
    source = tmp_path / "live.db"
    with sqlite3.connect(source) as conn:
        conn.execute("CREATE TABLE schema_version(version INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO schema_version VALUES(34)")
        conn.execute("CREATE TABLE evidence(id INTEGER PRIMARY KEY, payload TEXT)")
        conn.execute("INSERT INTO evidence VALUES(1,'data is safe')")
        conn.commit()
    partial = backups / resume.PARTIAL_NAME
    src = sqlite3.connect(source)
    dst = sqlite3.connect(partial)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    monkeypatch.setattr(resume, "require_independent_volume", lambda *_: None)
    monkeypatch.setattr(resume.time, "sleep", lambda _: None)
    monkeypatch.setattr(bridge, "STATUS", backups / "snapshot_status.json")
    mock_fcntl = types.ModuleType("fcntl")
    mock_fcntl.LOCK_EX = 2
    mock_fcntl.LOCK_NB = 4
    mock_fcntl.flock = lambda *_: None
    monkeypatch.setitem(sys.modules, "fcntl", mock_fcntl)
    return source, root, backups, partial


def test_resume_promotes_existing_complete_snapshot_only(recovery):
    source, root, backups, partial = recovery
    size = partial.stat().st_size
    target = resume.resume_snapshot(
        source=source, volume=root, backups=backups, production=False,
        min_expected_bytes=1,
    )
    assert target.is_file() and target.stat().st_size == size
    assert not partial.exists()
    manifest = json.loads((backups / (target.name + ".manifest.json")).read_text())
    assert manifest["verification_level"] == "routine"
    assert manifest["quick_check"] == "ok"
    assert manifest["integrity_check"] is None
    assert manifest["resumed_from_stopped_snapshot"] is True
    assert manifest["snapshot_sha256"] == bridge.sha256(target)
    assert json.loads((backups / "snapshot_status.json").read_text())["phase"] == "COMPLETE"
    with sqlite3.connect(target) as db:
        assert db.execute("SELECT payload FROM evidence").fetchone()[0] == "data is safe"


def test_resume_rejects_corruption_without_promotion(recovery):
    source, root, backups, partial = recovery
    partial.write_bytes(b"obviously not sqlite")
    with pytest.raises(sqlite3.DatabaseError):
        resume.resume_snapshot(
            source=source, volume=root, backups=backups,
            production=False, min_expected_bytes=1,
        )
    assert partial.exists()
    assert not (backups / resume.FINAL_NAME).exists()


def test_resume_rejects_existing_destination_without_touching_it(recovery):
    source, root, backups, partial = recovery
    destination = backups / resume.FINAL_NAME
    destination.write_bytes(b"do-not-touch")
    with pytest.raises(FileExistsError, match="ALREADY_PROMOTED"):
        resume.resume_snapshot(
            source=source, volume=root, backups=backups,
            production=False, min_expected_bytes=1,
        )
    assert destination.read_bytes() == b"do-not-touch"
    assert partial.exists()


def test_resume_fails_if_volume_guard_refuses(recovery, monkeypatch):
    source, root, backups, partial = recovery
    def reject(*_):
        raise RuntimeError("NOT_MOUNTED")
    monkeypatch.setattr(resume, "require_independent_volume", reject)
    with pytest.raises(RuntimeError, match="NOT_MOUNTED"):
        resume.resume_snapshot(
            source=source, volume=root, backups=backups,
            production=False, min_expected_bytes=1,
        )
    assert partial.exists()
