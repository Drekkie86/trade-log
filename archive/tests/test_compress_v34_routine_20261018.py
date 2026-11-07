from __future__ import annotations

import gzip
import json
import shutil
import sqlite3
import sys
import types
from pathlib import Path

import pytest

import christiania_compress_v34_routine_20261018 as comp
from src.operations.backup_verification import hash_snapshot


@pytest.fixture
def sample(tmp_path, monkeypatch):
    root = tmp_path / "volume"
    backups = root / "backups"
    backups.mkdir(parents=True)
    plain = backups / "christiania_backup_20261017T203934Z.db"
    conn = sqlite3.connect(plain)
    try:
        conn.execute("CREATE TABLE schema_version(version INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO schema_version VALUES(34)")
        conn.commit()
    finally:
        conn.close()
    digest = hash_snapshot(plain)
    evidence = {
        "schema_version": 34,
        "verification_level": "routine",
        "quick_check": "ok",
        "integrity_check": None,
        "foreign_key_violation_count": 0,
        "snapshot_method": "VACUUM_INTO",
        "snapshot_path": str(plain),
        "snapshot_bytes": plain.stat().st_size,
        "snapshot_sha256": digest,
    }
    (backups / (plain.name + ".manifest.json")).write_text(json.dumps(evidence))
    monkeypatch.setattr(comp, "STATUS", backups / "status.json")
    monkeypatch.setattr(comp, "RESERVE", 0)
    monkeypatch.setattr(comp, "preflight_old_points", lambda: None)
    fake_fcntl = types.ModuleType("fcntl")
    fake_fcntl.LOCK_EX = 2
    fake_fcntl.LOCK_NB = 4
    fake_fcntl.flock = lambda *_: None
    monkeypatch.setitem(sys.modules, "fcntl", fake_fcntl)
    return root, backups, plain, evidence


def test_roundtrip_compression_has_truthful_manifest(sample):
    root, backups, plain, evidence = sample
    compressed = comp.compress_routine(
        root=root, backups=backups, plain=plain, production=False,
    )
    assert compressed.is_file() and not plain.exists()
    manifest = json.loads((backups / (compressed.name + ".manifest.json")).read_text())
    assert manifest["format_version"] == 2
    assert manifest["verification_level"] == "routine"
    assert manifest["quick_check"] == "ok"
    assert manifest["integrity_check"] is None
    assert manifest["source_sha256"] == evidence["snapshot_sha256"]
    with gzip.open(compressed, "rb") as archive:
        assert archive.read().startswith(b"SQLite format 3")
    assert json.loads((backups / "status.json").read_text())["phase"] == "COMPLETE"


def test_compression_rejects_tampered_evidence_without_removing_source(sample):
    root, backups, plain, evidence = sample
    proof_path = backups / (plain.name + ".manifest.json")
    proof = json.loads(proof_path.read_text())
    proof["quick_check"] = "unknown"
    proof_path.write_text(json.dumps(proof))
    with pytest.raises(RuntimeError, match="PLAINTEXT_EVIDENCE_DISAGREES"):
        comp.compress_routine(root=root, backups=backups, plain=plain, production=False)
    assert plain.is_file()
    assert not list(backups.glob("*.db.gz"))


def test_compression_rejects_bad_source_hash_without_promoting(sample):
    root, backups, plain, evidence = sample
    proof_path = backups / (plain.name + ".manifest.json")
    proof = json.loads(proof_path.read_text())
    proof["snapshot_sha256"] = "0" * 64
    proof_path.write_text(json.dumps(proof))
    with pytest.raises(RuntimeError, match="PLAIN_SNAPSHOT_HASH_CHANGED"):
        comp.compress_routine(root=root, backups=backups, plain=plain, production=False)
    assert plain.is_file()
    assert not list(backups.glob("*.db.gz"))
