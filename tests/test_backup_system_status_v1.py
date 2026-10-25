"""System recovery status uses the supervisor plus v3 receipt, never the
metadata-only legacy inventory. Fail-closed without a deep DB read.
"""
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from src.database.repository import EXPECTED_SCHEMA_VERSION
from src.operations.backup_system_status_v1 import read_backup_system_status
from src.ui.home_pages import system_checks, system_verdict


NOW = datetime(2026, 10, 25, 15, 15, tzinfo=UTC)


def _evidence(tmp_path, *, observed=None, check="PASS"):
    backup = tmp_path/"backups"
    backup.mkdir(parents=True)
    archive=backup/"christiania_backup_20261025T003233Z.db.gz"
    archive.write_bytes(b"mock compressed source")
    # V3 receipt is schema/identity verification only. Do not decompress
    # a production-sized archive during a System page render.
    receipt={
        "format_version":3,
        "backup_filename":archive.name,
        "compression":"gzip",
        "snapshot_method":"VACUUM_INTO",
        "verification_level":"archive_stream_sha256_crc_plus_real_restore_structural",
        "restore_trial_completed":True,
        "compressed_size_bytes":archive.stat().st_size,
        "source_size_bytes":39727546368,
        "compressed_sha256":"c"*64,
        "source_sha256":"a"*64,
        "created_at":"2026-10-25T00:57:32Z",
        "schema_version":EXPECTED_SCHEMA_VERSION,
    }
    (backup/(archive.name+".manifest.json")).write_text(json.dumps(receipt))
    supervisor=tmp_path/"supervisor.json"
    supervisor.write_text(json.dumps({
        "observed_at":(observed or NOW-timedelta(minutes=1)).isoformat(),
        "checks":[{"name":"backup-recovery-point",
                   "passed":check=="PASS","state":check}],
    }))
    return backup,archive,supervisor,receipt


def test_verified_archive_after_independent_supervisor_check(tmp_path):
    directory,archive,snap,_ = _evidence(tmp_path)
    status=read_backup_system_status(
        supervisor_path=snap, backup_dir=directory, now=NOW,
    )
    assert status.state=="VERIFIED",status
    assert "schema v" in status.detail
    assert status.schema_version==EXPECTED_SCHEMA_VERSION
    assert status.latest_archive==archive.name


def test_metadata_inventory_cannot_override_authoritative_verified_archive(tmp_path):
    directory,_,snap,_=_evidence(tmp_path)
    status=read_backup_system_status(
        supervisor_path=snap,backup_dir=directory,now=NOW,
    )
    rows=system_checks(
        {"daemon_health":{"state":"HEALTHY"}},
        {"state":"READY","ready":True},
        {"total_files":5,"valid_files":0,"latest_valid_age_hours":None,
         "entries":[{"state":"NOT_REVERIFIED"}]},
        recovery=status.as_dict(),
    )
    assert dict((label, ok) for label,ok,_ in rows)["Backups"] is True
    assert "No valid backup found" not in str(rows)


def test_metadata_only_inventory_is_unknown_not_a_false_failure():
    rows=system_checks(
        {}, {"state":"NOT_PROBED"},
        {"total_files":5,"valid_files":0,"latest_valid_age_hours":None,
         "entries":[{"state":"NOT_REVERIFIED"}]},
    )
    backup=[r for r in rows if r[0]=="Backups"][0]
    assert backup[1] is None
    assert "not been checked" in backup[2]


def test_failed_or_stale_supervisor_cannot_paint_backup_green(tmp_path):
    directory,_,snap,_=_evidence(tmp_path,check="FAIL")
    failed=read_backup_system_status(
        supervisor_path=snap,backup_dir=directory,now=NOW,
    )
    assert failed.state=="FAILED"
    directory,_,snap,_=_evidence(tmp_path/"other",observed=NOW-timedelta(hours=2))
    stale=read_backup_system_status(
        supervisor_path=snap,backup_dir=directory,now=NOW,
    )
    assert stale.state=="STALE"
    rows=system_checks(
        {},{"state":"NOT_PROBED"},{},
        recovery=stale.as_dict(),
    )
    assert {label:ok for label,ok,_ in rows}["Backups"] is None


def test_missing_supervisor_or_bad_archive_receipt_fails_closed(tmp_path):
    directory,archive,snap,_=_evidence(tmp_path)
    missing=read_backup_system_status(
        supervisor_path=tmp_path/"no-file",backup_dir=directory,now=NOW,
    )
    assert missing.state=="UNVERIFIED"
    marker=directory/(archive.name+".manifest.json")
    manifest=json.loads(marker.read_text())
    manifest["restore_trial_completed"]=False
    marker.write_text(json.dumps(manifest))
    bad=read_backup_system_status(
        supervisor_path=snap,backup_dir=directory,now=NOW,
    )
    assert bad.state=="UNVERIFIED"


def test_actual_schema_mismatch_is_not_healthy(tmp_path):
    directory,archive,snap,_=_evidence(tmp_path)
    marker=directory/(archive.name+".manifest.json")
    manifest=json.loads(marker.read_text())
    manifest["schema_version"]=EXPECTED_SCHEMA_VERSION-1
    marker.write_text(json.dumps(manifest))
    result=read_backup_system_status(
        supervisor_path=snap,backup_dir=directory,now=NOW,
    )
    assert result.state=="UNVERIFIED"


def test_missing_check_and_future_supervisor_are_not_verified(tmp_path):
    directory,_,snap,_=_evidence(tmp_path)
    payload=json.loads(snap.read_text())
    payload["checks"]=[]
    snap.write_text(json.dumps(payload))
    assert read_backup_system_status(
        supervisor_path=snap,backup_dir=directory,now=NOW,
    ).state=="UNVERIFIED"
    payload["checks"]=[{"name":"backup-recovery-point","passed":True,"state":"PASS"}]
    payload["observed_at"]=(NOW+timedelta(minutes=10)).isoformat()
    snap.write_text(json.dumps(payload))
    assert read_backup_system_status(
        supervisor_path=snap,backup_dir=directory,now=NOW,
    ).state=="UNVERIFIED"


def test_matching_independent_restore_audit_is_explicit(tmp_path):
    directory,archive,snap,_=_evidence(tmp_path)
    audit={
        "archive":archive.name,
        "phase":"PASSED",
        "schema_version":EXPECTED_SCHEMA_VERSION,
        "verification_level":"full_byte_hash_gzip_crc_and_separate_sqlite_read",
        "restored_size_bytes":39727546368,
        "at_utc":"2026-10-25T03:43:37Z",
    }
    (directory/"volume_backup_restore_audit_status.json").write_text(json.dumps(audit))
    report=read_backup_system_status(
        supervisor_path=snap,backup_dir=directory,now=NOW,
    )
    assert report.state=="VERIFIED",report
    assert "Independent full-restore audit PASSED" in report.detail

    audit["phase"]="FAILED"
    (directory/"volume_backup_restore_audit_status.json").write_text(json.dumps(audit))
    refused=read_backup_system_status(
        supervisor_path=snap,backup_dir=directory,now=NOW,
    )
    assert refused.state=="FAILED"


def test_older_audit_does_not_discredit_new_nightly_backup(tmp_path):
    directory,archive,snap,_=_evidence(tmp_path)
    audit={
        "archive":"older_backup.db.gz",
        "phase":"PASSED",
        "schema_version":EXPECTED_SCHEMA_VERSION,
        "verification_level":"full_byte_hash_gzip_crc_and_separate_sqlite_read",
        "restored_size_bytes":39727546368,
        "at_utc":"2026-10-24T03:43:37Z",
    }
    (directory/"volume_backup_restore_audit_status.json").write_text(json.dumps(audit))
    report=read_backup_system_status(
        supervisor_path=snap,backup_dir=directory,now=NOW,
    )
    assert report.state=="VERIFIED"
    assert "independent audit pending" in report.detail
