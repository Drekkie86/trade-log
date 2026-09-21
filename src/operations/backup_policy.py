from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from src.config import get_runtime_setting
from src.database.repository import (
    EXPECTED_SCHEMA_VERSION,
    resolve_db_path,
)
from src.operations.backup_compression import (
    backup_data_files,
    load_compressed_manifest,
)
from src.operations.sqlite_runtime import resolve_backup_dir


DEFAULT_BACKUP_MAX_AGE_HOURS = 168.0


@dataclass(frozen=True)
class BackupDecision:
    due: bool
    reason: str
    observed_at: str
    latest_backup_path: str | None
    latest_backup_age_hours: float | None
    latest_backup_schema_version: int | None
    current_schema_version: int
    latest_completed_research_at: str | None
    max_age_hours: float

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _setting_nonnegative_float(
    name: str,
    default: float,
) -> float:
    raw = get_runtime_setting(name)
    if raw in (None, ""):
        return default

    value = float(raw)
    if value < 0:
        raise ValueError(
            f"{name} cannot be negative."
        )
    return value


def _parse_utc(value: object) -> datetime | None:
    if value in (None, ""):
        return None

    try:
        parsed = datetime.fromisoformat(
            str(value).replace("Z", "+00:00")
        )
    except (TypeError, ValueError):
        return None

    if parsed.tzinfo is None:
        return None

    return parsed.astimezone(UTC)


def _latest_backup(
    directory: Path,
) -> tuple[Path | None, int | None]:
    candidates = sorted(
        backup_data_files(directory),
        key=lambda path: path.stat().st_mtime_ns,
        reverse=True,
    )

    if not candidates:
        return None, None

    latest = candidates[0]

    if latest.name.endswith(".db.gz"):
        try:
            version = int(
                load_compressed_manifest(
                    latest
                ).schema_version
            )
        except Exception:
            version = None
        return latest, version

    try:
        uri = latest.resolve().as_uri() + "?mode=ro"
        conn = sqlite3.connect(
            uri,
            uri=True,
            timeout=30.0,
        )
        try:
            row = conn.execute(
                "SELECT MAX(version) FROM schema_version"
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return latest, None

    version = (
        None
        if row is None or row[0] is None
        else int(row[0])
    )
    return latest, version


def _latest_completed_research(
    db_path: Path,
) -> datetime | None:
    uri = db_path.resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(
        uri,
        uri=True,
        timeout=30.0,
    )

    try:
        row = conn.execute(
            """
            SELECT MAX(completed_at)
            FROM research_daemon_iterations
            WHERE status = 'COMPLETED'
              AND completed_at IS NOT NULL;
            """
        ).fetchone()
    except sqlite3.Error:
        return None
    finally:
        conn.close()

    if row is None:
        return None

    return _parse_utc(row[0])


def evaluate_backup_due(
    *,
    db_path: str | Path | None = None,
    backup_dir: str | Path | None = None,
    now: datetime | None = None,
    max_age_hours: float | None = None,
) -> BackupDecision:
    observed = (
        datetime.now(UTC)
        if now is None
        else now.astimezone(UTC)
    )

    maximum_age = (
        _setting_nonnegative_float(
            "CHRISTIANIA_BACKUP_MAX_AGE_HOURS",
            DEFAULT_BACKUP_MAX_AGE_HOURS,
        )
        if max_age_hours is None
        else float(max_age_hours)
    )

    if maximum_age < 0:
        raise ValueError(
            "max_age_hours cannot be negative."
        )

    database = resolve_db_path(db_path)
    directory = resolve_backup_dir(backup_dir)

    latest, backup_schema = _latest_backup(
        directory
    )
    latest_research = _latest_completed_research(
        database
    )

    latest_path = (
        None if latest is None else str(latest)
    )
    latest_age = None

    if latest is not None:
        modified = datetime.fromtimestamp(
            latest.stat().st_mtime,
            tz=UTC,
        )
        latest_age = max(
            0.0,
            (
                observed - modified
            ).total_seconds() / 3600.0,
        )
    else:
        modified = None

    if latest is None:
        due = True
        reason = "NO_RECOVERY_POINT"
    elif backup_schema != EXPECTED_SCHEMA_VERSION:
        due = True
        reason = "LATEST_BACKUP_SCHEMA_MISMATCH"
    elif (
        latest_age is not None
        and latest_age >= maximum_age
    ):
        due = True
        reason = "MAXIMUM_RECOVERY_POINT_AGE_EXCEEDED"
    elif (
        latest_research is not None
        and modified is not None
        and latest_research > modified
    ):
        due = True
        reason = "NEW_COMPLETED_RESEARCH_SINCE_BACKUP"
    else:
        due = False
        reason = "NO_NEW_COMPLETED_RESEARCH"

    return BackupDecision(
        due=due,
        reason=reason,
        observed_at=(
            observed.isoformat()
            .replace("+00:00", "Z")
        ),
        latest_backup_path=latest_path,
        latest_backup_age_hours=latest_age,
        latest_backup_schema_version=backup_schema,
        current_schema_version=EXPECTED_SCHEMA_VERSION,
        latest_completed_research_at=(
            None
            if latest_research is None
            else latest_research.isoformat()
            .replace("+00:00", "Z")
        ),
        max_age_hours=maximum_age,
    )
