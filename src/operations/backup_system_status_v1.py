"""Metadata-only System backup readout tied to the actual RC0 recovery policy.

Do not confuse the UI's NOT_REVERIFIED *fast inventory* with a failed
production backup. A green state needs a fresh supervisor PASS plus
a same-schema completed v3 recovery receipt for the latest archive.
Never decompress a multi-gigabyte archive or run SQLite quick_check here.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from src.database.repository import EXPECTED_SCHEMA_VERSION
from src.operations.backup_policy import _latest_backup, _volume_v3_manifest_schema
from src.operations.sqlite_runtime import resolve_backup_dir

DEFAULT_SUPERVISOR_PATH = Path(
    "/var/lib/christiania/audit/rc0_supervisor_status.json"
)
MAX_SUPERVISOR_AGE = timedelta(minutes=20)
MAX_STATUS_BYTES = 128 * 1024


@dataclass(frozen=True)
class BackupSystemStatus:
    state: str
    detail: str
    latest_archive: str | None = None
    schema_version: int | None = None
    supervisor_observed_at: str | None = None

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _aware(raw: object) -> datetime | None:
    if not isinstance(raw, str):
        return None
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if value.tzinfo is None or value.utcoffset() is None:
            return None
        return value.astimezone(UTC)
    except (ValueError, OverflowError):
        return None


def _bounded_json(path: Path) -> object:
    if not path.is_file() or path.stat().st_size > MAX_STATUS_BYTES:
        raise ValueError("STATUS_FILE_MISSING_OR_OVERSIZED")
    return json.loads(path.read_text(encoding="utf-8"))


def read_backup_system_status(
    *,
    supervisor_path: str | Path = DEFAULT_SUPERVISOR_PATH,
    backup_dir: str | Path | None = None,
    now: datetime | None = None,
) -> BackupSystemStatus:
    """Cheap, independent and fail-closed backup-health read for System UI.

    A supervisor *passing* is only useful if it is recent and the latest
    on-disk v3 manifest agrees on schema and completed restore verification.
    """
    observed = datetime.now(UTC) if now is None else now.astimezone(UTC)
    try:
        snapshot = _bounded_json(Path(supervisor_path))
        if not isinstance(snapshot, dict):
            raise ValueError("SUPERVISOR_MALFORMED")
        at = _aware(snapshot.get("observed_at"))
        if at is None or at > observed + timedelta(seconds=30):
            return BackupSystemStatus(
                "UNVERIFIED", "Supervisor recovery status has no valid timestamp."
            )
        if observed - at > MAX_SUPERVISOR_AGE:
            return BackupSystemStatus(
                "STALE", "The last supervisor backup check is stale.",
                supervisor_observed_at=at.isoformat(),
            )
        checks = snapshot.get("checks")
        if not isinstance(checks, list):
            raise ValueError("SUPERVISOR_CHECKS_MISSING")
        matches = [
            x for x in checks if isinstance(x, dict)
            and x.get("name") == "backup-recovery-point"
        ]
        if len(matches) != 1:
            return BackupSystemStatus(
                "UNVERIFIED", "No unambiguous backup recovery check is available.",
                supervisor_observed_at=at.isoformat(),
            )
        check = matches[0]
        if check.get("passed") is not True or check.get("state") != "PASS":
            return BackupSystemStatus(
                "FAILED", "Supervisor reports a recovery-point failure.",
                supervisor_observed_at=at.isoformat(),
            )
        # Do not silently accept a v3 format based on its schema integer.
        # _latest_backup validates its receipt, archive size, identity and
        # completed restore marker without reading/decompressing the archive.
        latest, schema, created_at = _latest_backup(resolve_backup_dir(backup_dir))
        if latest is None or schema != EXPECTED_SCHEMA_VERSION or created_at is None:
            return BackupSystemStatus(
                "UNVERIFIED",
                "The latest archive or its completed recovery receipt cannot be validated.",
                supervisor_observed_at=at.isoformat(),
            )
        if latest.suffixes[-2:] != [".db", ".gz"]:
            # Plain databases may be valid, but require deep explicit checks.
            return BackupSystemStatus(
                "UNVERIFIED",
                "Latest backup is not a verified compressed recovery archive.",
                supervisor_observed_at=at.isoformat(),
            )
        # v1/v2 manifests predate the independently verified volume restore
        # pipeline and must not be labelled 'verified restore' by this UI.
        try:
            _volume_v3_manifest_schema(latest)
        except (ValueError, OSError, TypeError):
            return BackupSystemStatus(
                "UNVERIFIED",
                "No completed independent-volume restore receipt for the latest backup.",
                supervisor_observed_at=at.isoformat(),
            )
        backup_age = (observed - created_at).total_seconds() / 3600
        if backup_age < -0.01 or backup_age > 168:
            return BackupSystemStatus(
                "STALE",
                "The latest verified recovery point is outside the weekly policy window.",
                latest_archive=latest.name,
                schema_version=schema,
                supervisor_observed_at=at.isoformat(),
            )
        # An independent weekly restore audit is stronger than the nightly
        # writer's restore trial. Report it only if it matches THIS archive.
        audit_summary = "Writer restore verified; independent audit pending."
        audit_path = latest.parent / "volume_backup_restore_audit_status.json"
        try:
            audit = _bounded_json(audit_path)
        except (OSError, ValueError, json.JSONDecodeError):
            audit = None
        if isinstance(audit, dict) and audit.get("archive") == latest.name:
            if (
                audit.get("phase") != "PASSED"
                or audit.get("schema_version") != schema
                or audit.get("verification_level")
                != "full_byte_hash_gzip_crc_and_separate_sqlite_read"
                or not isinstance(audit.get("restored_size_bytes"), int)
                or audit.get("restored_size_bytes") <= 0
                or _aware(audit.get("at_utc")) is None
            ):
                return BackupSystemStatus(
                    "FAILED", "Latest archive's independent restore audit failed.",
                    latest_archive=latest.name,
                    schema_version=schema,
                    supervisor_observed_at=at.isoformat(),
                )
            audit_summary = "Independent full-restore audit PASSED."
        return BackupSystemStatus(
            "VERIFIED",
            f"Recovery point: schema v{schema}, "
            f"archive age {backup_age:.1f} h. {audit_summary} "
            "Supervisor recovery check passed.",
            latest_archive=latest.name,
            schema_version=schema,
            supervisor_observed_at=at.isoformat(),
        )
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return BackupSystemStatus(
            "UNVERIFIED",
            "Recovery evidence could not be read; this is not proof that no backup exists.",
        )
