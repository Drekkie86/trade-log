"""Verify the CURRENT independent-volume v3 restore proof, not retired scheduler JSON.

Fail closed using the completed immutable archive manifest plus the *separate*
successful weekly full-restore audit, matching the exact same archive.
This is a bounded metadata gate; it does NOT redo the multi-GB hash/audit.
"""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from src.operations.backup_policy import _latest_backup, _volume_v3_manifest_schema

FULL_AUDIT_LEVEL = "full_byte_hash_gzip_crc_and_separate_sqlite_read"
MAX_PROOF_BYTES = 64 * 1024


def _aware(raw: object) -> datetime:
    if not isinstance(raw, str):
        raise ValueError("RECOVERY_TIMESTAMP_MISSING")
    value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("RECOVERY_TIMESTAMP_NOT_AWARE")
    return value.astimezone(UTC)


def _read_proof(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        raise ValueError("RECOVERY_PROOF_MISSING_OR_SYMLINK")
    size = path.stat().st_size
    if not 0 < size <= MAX_PROOF_BYTES:
        raise ValueError("RECOVERY_PROOF_SIZE_INVALID")
    proof = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(proof, dict):
        raise ValueError("RECOVERY_PROOF_NOT_OBJECT")
    return proof


def _on_independent_device(source: Path, backup_dir: Path) -> bool:
    return os.stat(source).st_dev != os.stat(backup_dir).st_dev


def verify_recent_restored_archive(
    *, source: Path, backup_dir: Path, expected_schema_version: int,
    now: datetime | None = None,
) -> dict[str, object]:
    """Confirm exact latest archive, v3 manifest and completed full-restore audit.

    The archived backup may be older than a running research daemon's DB; the
    source size must still be in the same range and the supervisor separately
    controls whether a new recovery point is due.
    """
    actual_now = (now or datetime.now(UTC)).astimezone(UTC)
    if (not source.is_file() or source.is_symlink()
            or not backup_dir.is_dir() or backup_dir.is_symlink()):
        raise RuntimeError("LARGE_RELEASE_SOURCE_OR_BACKUP_DIR_MISSING")
    if not _on_independent_device(source, backup_dir):
        raise RuntimeError("LARGE_RELEASE_BACKUP_NOT_ON_INDEPENDENT_VOLUME")
    try:
        latest, schema, captured = _latest_backup(backup_dir)
        if (latest is None or latest.is_symlink() or not latest.is_file()
                or not latest.name.endswith(".db.gz")
                or not latest.resolve().is_relative_to(backup_dir.resolve())
                or schema != expected_schema_version or captured is None):
            raise ValueError("latest archive or schema not verified")
        if _volume_v3_manifest_schema(latest) != expected_schema_version:
            raise ValueError("latest archive lacks completed v3 restore")
        manifest = _read_proof(Path(str(latest) + ".manifest.json"))
        audit = _read_proof(backup_dir / "volume_backup_restore_audit_status.json")
        completed = _aware(audit.get("at_utc"))
        archived = _aware(manifest.get("created_at"))
        age = actual_now - completed
        archive_age = actual_now - archived
        if (not timedelta(0) <= age <= timedelta(hours=36)
                or not timedelta(0) <= archive_age <= timedelta(hours=36)
                or completed < archived or archived < captured):
            raise ValueError("archive/audit dates stale or inconsistent")
        if (audit.get("phase") != "PASSED"
                or audit.get("verification_level") != FULL_AUDIT_LEVEL
                or audit.get("archive") != latest.name
                or type(audit.get("schema_version")) is not int
                or audit["schema_version"] != expected_schema_version):
            raise ValueError("no matching independently completed full restore")
        bytes_restored = audit.get("restored_size_bytes")
        expected_bytes = manifest.get("source_size_bytes")
        if (type(bytes_restored) is not int
                or type(expected_bytes) is not int
                or bytes_restored <= 0 or bytes_restored != expected_bytes
                or bytes_restored < source.stat().st_size * 0.90):
            raise ValueError("restored source size identity is inconsistent")
        return {
            "restore_completed_at": completed.isoformat(),
            "schema_version": expected_schema_version,
            "restored_bytes": bytes_restored,
            "archive_path": str(latest),
        }
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError("LARGE_RELEASE_RESTORE_AUDIT_NOT_VERIFIED") from exc
