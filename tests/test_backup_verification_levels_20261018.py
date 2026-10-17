"""Regression contracts for truthful, bounded routine backup verification."""
from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from src.database.repository import EXPECTED_SCHEMA_VERSION
from src.operations import backup_compression
from src.operations.backup_compression import (
    compress_verified_backup, load_compressed_manifest, manifest_path_for,
    verify_compressed_backup,
)
from src.operations.backup_verification import (
    evidence_path_for, hash_snapshot, read_plain_evidence,
    verify_sqlite_snapshot,
)
from src.operations.sqlite_runtime import create_verified_backup


def make_db(path: Path, *, violation: bool = False):
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("CREATE TABLE schema_version(version INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO schema_version VALUES(?)", (EXPECTED_SCHEMA_VERSION,))
        conn.execute("CREATE TABLE parent(id INTEGER PRIMARY KEY)")
        conn.execute("CREATE TABLE child(id INTEGER PRIMARY KEY, pid INTEGER REFERENCES parent(id))")
        conn.execute("INSERT INTO child VALUES(1, ?)", (33 if violation else None,))
        conn.commit()


def test_routine_and_deep_are_distinct(tmp_path):
    db = tmp_path / "sample.db"
    make_db(db)
    routine = verify_sqlite_snapshot(db, expected_schema=EXPECTED_SCHEMA_VERSION)
    assert routine.level == "routine"
    assert routine.quick_check == "ok"
    assert routine.integrity_check is None
    deep = verify_sqlite_snapshot(db, expected_schema=EXPECTED_SCHEMA_VERSION, level="deep")
    assert deep.level == "deep"
    assert deep.quick_check is None
    assert deep.integrity_check == "ok"


def test_routine_rejects_fk_violation_without_promoting(tmp_path):
    source = tmp_path / "source.db"
    make_db(source, violation=True)
    with pytest.raises(RuntimeError, match="foreign_key_check"):
        create_verified_backup(db_path=source, backup_dir=tmp_path / "backups")
    assert not list((tmp_path / "backups").glob("christiania_backup_*.db"))


def test_compress_preserves_routine_evidence_and_rejects_tampering(tmp_path):
    source = tmp_path / "source.db"
    make_db(source)
    result = create_verified_backup(db_path=source, backup_dir=tmp_path / "backups")
    plain = Path(result.backup_path)
    verified = read_plain_evidence(plain, source_sha256=hash_snapshot(plain))
    assert verified.verification_level == "routine"
    assert verified.integrity_check is None
    manifest_path = evidence_path_for(plain)
    assert manifest_path.exists()

    compressed = Path(compress_verified_backup(plain).compressed_path)
    assert not plain.exists()
    assert not manifest_path.exists()
    manifest = load_compressed_manifest(compressed)
    assert manifest.format_version == 2
    assert manifest.verification_level == "routine"
    assert manifest.quick_check == "ok"
    assert manifest.integrity_check is None
    assert verify_compressed_backup(compressed, deep_payload=True) == manifest

    data = json.loads(manifest_path_for(compressed).read_text())
    data["verification_level"] = "deep"
    manifest_path_for(compressed).write_text(json.dumps(data))
    with pytest.raises(RuntimeError, match="verification"):
        verify_compressed_backup(compressed)


def test_compression_fails_closed_if_source_evidence_is_false(tmp_path):
    source = tmp_path / "source.db"
    make_db(source)
    result = create_verified_backup(db_path=source, backup_dir=tmp_path / "backups")
    plain = Path(result.backup_path)
    evidence = evidence_path_for(plain)
    data = json.loads(evidence.read_text())
    data["source_sha256"] = "0" * 64
    evidence.write_text(json.dumps(data))
    with pytest.raises(RuntimeError, match="does not match source bytes"):
        compress_verified_backup(plain)
    assert plain.exists() and evidence.exists()
    assert not Path(str(plain) + ".gz").exists()


def test_existing_verified_files_not_pruned_during_routine_creation(tmp_path):
    source = tmp_path / "source.db"
    make_db(source)
    backups = tmp_path / "backups"
    backups.mkdir()
    previous = []
    for index in range(3):
        filename = backups / f"christiania_backup_2026010{index+1}T000000Z.db"
        shutil.copy2(source, filename)
        previous.append(filename)
    result = create_verified_backup(db_path=source, backup_dir=backups, retention=2)
    assert result.pruned_count == 0
    assert all(p.exists() for p in previous)


def test_wrong_schema_and_impossible_deadline_fail_closed(tmp_path, monkeypatch):
    db = tmp_path / "db.db"
    make_db(db)
    with pytest.raises(RuntimeError, match="schema"):
        verify_sqlite_snapshot(db, expected_schema=34)
    with pytest.raises(ValueError, match="timeout"):
        verify_sqlite_snapshot(db, expected_schema=EXPECTED_SCHEMA_VERSION, max_seconds=0)
