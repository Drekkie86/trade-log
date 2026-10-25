"""Current independent volume restore receipts must survive transition to v38.

Pure synthetic files; never claims that a fake archive was actually restored.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from src.operations import verified_volume_recovery_v1 as v
from src.operations.deployment_transition_gate import _verified_volume_backup


NOW = datetime(2026, 10, 25, 21, 0, tzinfo=UTC)


@pytest.fixture
def proof(tmp_path, monkeypatch):
    source = tmp_path / "live" / "trade_log.db"
    source.parent.mkdir()
    with sqlite3.connect(source) as conn:
        conn.execute("CREATE TABLE schema_version(version INTEGER NOT NULL)")
        conn.execute("INSERT INTO schema_version VALUES (37)")
    directory = tmp_path / "volume" / "backups"
    directory.mkdir(parents=True)
    latest = directory / "christiania_backup_20261025T200000Z.db.gz"
    data = b"test-archive-bytes" * 140
    latest.write_bytes(data)
    size = source.stat().st_size
    manifest = {
        "format_version": 3,
        "backup_filename": latest.name,
        "compression": "gzip",
        "snapshot_method": "VACUUM_INTO",
        "verification_level": "archive_stream_sha256_crc_plus_real_restore_structural",
        "restore_trial_completed": True,
        "source_sha256": hashlib.sha256(b"test-source").hexdigest(),
        "compressed_sha256": hashlib.sha256(data).hexdigest(),
        "source_size_bytes": size,
        "compressed_size_bytes": len(data),
        "created_at": "2026-10-25T20:02:00Z",
        "schema_version": 37,
    }
    manifest_path = Path(str(latest) + ".manifest.json")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    audit = {
        "archive": latest.name,
        "at_utc": "2026-10-25T20:10:00Z",
        "phase": "PASSED",
        "restored_size_bytes": size,
        "schema_version": 37,
        "verification_level": v.FULL_AUDIT_LEVEL,
    }
    audit_path = directory / "volume_backup_restore_audit_status.json"
    audit_path.write_text(json.dumps(audit), encoding="utf-8")
    # The tempfile filesystem cannot create its own device; this patch
    # replaces only that environmental prerequisite, not evidence checks.
    monkeypatch.setattr(v, "_on_independent_device", lambda *_: True)
    return source, directory, manifest_path, audit_path


def test_current_v3_archive_and_completed_independent_audit_qualify(proof):
    source, directory, _, _ = proof
    result = v.verify_recent_restored_archive(
        source=source, backup_dir=directory,
        expected_schema_version=37, now=NOW,
    )
    assert result["schema_version"] == 37
    assert result["restored_bytes"] == source.stat().st_size
    assert result["archive_path"].endswith(".db.gz")


@pytest.mark.parametrize("change", [
    {"phase": "AUDITING"},
    {"archive": "different_archive.db.gz"},
    {"schema_version": 36},
    {"restored_size_bytes": 1},
    {"verification_level": "metadata-only"},
    {"at_utc": "2026-10-20T20:10:00Z"},
])
def test_wrong_stale_or_partial_restore_receipts_fail_closed(proof, change):
    source, directory, _, audit_path = proof
    audit = json.loads(audit_path.read_text())
    audit.update(change)
    audit_path.write_text(json.dumps(audit))
    with pytest.raises(RuntimeError, match="AUDIT_NOT_VERIFIED"):
        v.verify_recent_restored_archive(
            source=source, backup_dir=directory,
            expected_schema_version=37, now=NOW,
        )


def test_corrupted_manifest_blocks_release(proof):
    source, directory, manifest_path, _ = proof
    manifest = json.loads(manifest_path.read_text())
    manifest["restore_trial_completed"] = False
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(RuntimeError, match="AUDIT_NOT_VERIFIED"):
        v.verify_recent_restored_archive(
            source=source, backup_dir=directory,
            expected_schema_version=37, now=NOW,
        )


def test_old_scheduler_progress_is_not_evidence_and_success_is_independent(proof, monkeypatch):
    source, directory, _, audit_path = proof
    volume = directory.parent
    monkeypatch.setattr(Path, "is_mount", lambda p: p == volume)
    scheduler = directory / "volume_backup_scheduler_status.json"
    scheduler.write_text('{"phase":"AUDIT_RESTORE"}')
    assert _verified_volume_backup(scheduler, volume, source, now=NOW)
    audit_path.unlink()
    assert not _verified_volume_backup(scheduler, volume, source, now=NOW)


def test_source_and_backup_same_filesystem_rejected_without_environment_patch(proof, monkeypatch):
    source, directory, _, _ = proof
    monkeypatch.setattr(v, "_on_independent_device", lambda *_: False)
    with pytest.raises(RuntimeError, match="INDEPENDENT_VOLUME"):
        v.verify_recent_restored_archive(
            source=source, backup_dir=directory,
            expected_schema_version=37, now=NOW,
        )
