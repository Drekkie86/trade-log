"""Production RC0 backup policy accepts only VERIFIED v3 restore manifests."""
from __future__ import annotations

import gzip
import json
from datetime import UTC, datetime, timedelta

import pytest

from src.database.repository import EXPECTED_SCHEMA_VERSION
from src.operations.backup_policy import evaluate_backup_due
from tests.test_backup_policy_v2 import _seed_db, _backup_copy


NOW = datetime(2026, 10, 25, 13, 20, tzinfo=UTC)
CAPTURE = datetime(2026, 10, 25, 0, 32, 33, tzinfo=UTC)


def _v3_fixture(tmp_path, *, schema=None, completed=True):
    db = tmp_path / "trade_log.db"
    backups = tmp_path / "backups"
    backups.mkdir()
    _seed_db(db, ["2026-10-23T19:47:50.048000Z"])
    _backup_copy(
        db, backups,
        captured_at=CAPTURE - timedelta(days=5),
    )
    archive = backups / "christiania_backup_20261025T003233Z.db.gz"
    archive.write_bytes(gzip.compress(b"tiny synthetic test backup"))
    sha = "a" * 64
    manifest = {
        "backup_filename": archive.name,
        "compressed_sha256": "b" * 64,
        "compressed_size_bytes": archive.stat().st_size,
        "compression": "gzip",
        "created_at": "2026-10-25T00:57:32.652557+00:00",
        "foreign_key_check": "NOT_RUN",
        "format_version": 3,
        "full_sqlite_integrity_check": None,
        "quick_check": None,
        "restore_trial_completed": completed,
        "schema_version": (
            EXPECTED_SCHEMA_VERSION if schema is None else schema
        ),
        "snapshot_method": "VACUUM_INTO",
        "source_filename": ".christiania_backup_20261025T003233Z.incomplete.db",
        "source_sha256": sha,
        "source_size_bytes": 39727546368,
        "verification_level": "archive_stream_sha256_crc_plus_real_restore_structural",
    }
    marker = backups / (archive.name + ".manifest.json")
    marker.write_text(json.dumps(manifest))
    return db, backups, archive, marker, manifest


def due(db, backups):
    return evaluate_backup_due(
        db_path=db, backup_dir=backups, now=NOW,
        max_age_hours=168, min_new_research_iterations=25,
    )


def test_verified_volume_v3_restore_matches_live_schema_and_stops_false_alarm(tmp_path):
    db, backups, archive, *_ = _v3_fixture(tmp_path)
    decision = due(db, backups)
    assert not decision.due
    assert decision.reason == "NO_NEW_COMPLETED_RESEARCH"
    assert decision.latest_backup_path == str(archive)
    assert decision.latest_backup_schema_version == EXPECTED_SCHEMA_VERSION
    assert decision.latest_backup_age_hours == pytest.approx(
        (NOW-CAPTURE).total_seconds()/3600
    )


@pytest.mark.parametrize("change", [
    {"restore_trial_completed": False},
    {"verification_level": "gzip_only"},
    {"snapshot_method": "UNKNOWN"},
    {"compressed_size_bytes": 1},
    {"compressed_sha256": "z" * 64},
    {"schema_version": None},
    {"backup_filename": "swapped-file.db.gz"},
    {"created_at": "2026-10-24T00:57:32Z"},
])
def test_unverified_or_inconsistent_v3_manifest_is_never_accepted(tmp_path, change):
    db, backups, archive, marker, manifest = _v3_fixture(tmp_path)
    manifest.update(change)
    marker.write_text(json.dumps(manifest))
    result = due(db, backups)
    assert result.due
    assert result.reason == "LATEST_BACKUP_UNVERIFIED"
    assert result.latest_backup_path == str(archive)


def test_real_schema_mismatch_remains_a_release_blocker(tmp_path):
    db, backups, archive, *_ = _v3_fixture(
        tmp_path, schema=EXPECTED_SCHEMA_VERSION-1
    )
    decision = due(db, backups)
    assert decision.due
    assert decision.reason == "LATEST_BACKUP_SCHEMA_MISMATCH"


def test_corrupt_json_manifest_fails_closed(tmp_path):
    db, backups, _, marker, _ = _v3_fixture(tmp_path)
    marker.write_text("{this is not json")
    decision = due(db, backups)
    assert decision.due
    assert decision.reason == "LATEST_BACKUP_UNVERIFIED"
