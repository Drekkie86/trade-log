from __future__ import annotations

import re
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
DEFAULT_BACKUP_MIN_NEW_RESEARCH_ITERATIONS = 25

_BACKUP_STAMP = re.compile(
    r"^christiania_backup_(\d{8}T\d{6}Z)\.db(?:\.gz)?$"
)


@dataclass(frozen=True)
class BackupDecision:
    due: bool
    reason: str
    observed_at: str
    latest_backup_path: str | None
    latest_backup_age_hours: float | None
    latest_backup_captured_at: str | None
    latest_backup_schema_version: int | None
    current_schema_version: int
    latest_completed_research_at: str | None
    completed_research_since_backup: int
    min_new_research_iterations: int
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


def _setting_positive_int(
    name: str,
    default: int,
) -> int:
    raw = get_runtime_setting(name)
    if raw in (None, ""):
        return default

    value = int(raw)
    if value < 1:
        raise ValueError(
            f"{name} must be >= 1."
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


def _backup_capture_time(path: Path) -> datetime:
    match = _BACKUP_STAMP.match(path.name)

    if match is not None:
        return datetime.strptime(
            match.group(1),
            "%Y%m%dT%H%M%SZ",
        ).replace(tzinfo=UTC)

    return datetime.fromtimestamp(
        path.stat().st_mtime,
        tz=UTC,
    )


def _latest_backup(
    directory: Path,
) -> tuple[
    Path | None,
    int | None,
    datetime | None,
]:
    candidates = sorted(
        backup_data_files(directory),
        key=_backup_capture_time,
        reverse=True,
    )

    if not candidates:
        return None, None, None

    latest = candidates[0]
    captured_at = _backup_capture_time(latest)

    if latest.name.endswith(".db.gz"):
        try:
            version = int(
                load_compressed_manifest(
                    latest
                ).schema_version
            )
        except Exception:
            version = None
        return latest, version, captured_at

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
        return latest, None, captured_at

    version = (
        None
        if row is None or row[0] is None
        else int(row[0])
    )
    return latest, version, captured_at


def _research_stats(
    db_path: Path,
    *,
    after: datetime | None,
) -> tuple[int, datetime | None]:
    uri = db_path.resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(
        uri,
        uri=True,
        timeout=30.0,
    )

    try:
        latest_row = conn.execute(
            """
            SELECT MAX(completed_at)
            FROM research_daemon_iterations
            WHERE status = 'COMPLETED'
              AND completed_at IS NOT NULL;
            """
        ).fetchone()

        if after is None:
            count_since = 0
        else:
            after_iso = (
                after.astimezone(UTC)
                .isoformat()
                .replace("+00:00", "Z")
            )
            count_row = conn.execute(
                """
                SELECT COUNT(*)
                FROM research_daemon_iterations
                WHERE status = 'COMPLETED'
                  AND completed_at IS NOT NULL
                  AND julianday(completed_at) > julianday(?);
                """,
                (after_iso,),
            ).fetchone()
            count_since = int(
                0
                if count_row is None
                else count_row[0] or 0
            )
    except sqlite3.Error:
        return 0, None
    finally:
        conn.close()

    latest = (
        None
        if latest_row is None
        else _parse_utc(latest_row[0])
    )

    return count_since, latest


def evaluate_backup_due(
    *,
    db_path: str | Path | None = None,
    backup_dir: str | Path | None = None,
    now: datetime | None = None,
    max_age_hours: float | None = None,
    min_new_research_iterations: int | None = None,
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

    minimum_research = (
        _setting_positive_int(
            "CHRISTIANIA_BACKUP_MIN_NEW_RESEARCH_ITERATIONS",
            DEFAULT_BACKUP_MIN_NEW_RESEARCH_ITERATIONS,
        )
        if min_new_research_iterations is None
        else int(min_new_research_iterations)
    )
    if minimum_research < 1:
        raise ValueError(
            "min_new_research_iterations must be >= 1."
        )

    database = resolve_db_path(db_path)
    directory = resolve_backup_dir(backup_dir)

    (
        latest,
        backup_schema,
        captured_at,
    ) = _latest_backup(directory)

    (
        completed_since,
        latest_research,
    ) = _research_stats(
        database,
        after=captured_at,
    )

    latest_path = (
        None if latest is None else str(latest)
    )
    latest_age = None

    if captured_at is not None:
        latest_age = max(
            0.0,
            (
                observed - captured_at
            ).total_seconds() / 3600.0,
        )

    if latest is None:
        due = True
        reason = "NO_RECOVERY_POINT"
    elif backup_schema != EXPECTED_SCHEMA_VERSION:
        due = True
        reason = "LATEST_BACKUP_SCHEMA_MISMATCH"
    elif completed_since >= minimum_research:
        due = True
        reason = "MATERIAL_NEW_RESEARCH_ACCUMULATED"
    elif (
        completed_since > 0
        and latest_age is not None
        and latest_age >= maximum_age
    ):
        due = True
        reason = "UNPROTECTED_RESEARCH_MAX_AGE_EXCEEDED"
    elif completed_since > 0:
        due = False
        reason = "NEW_RESEARCH_BELOW_MATERIALITY_THRESHOLD"
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
        latest_backup_captured_at=(
            None
            if captured_at is None
            else captured_at.isoformat()
            .replace("+00:00", "Z")
        ),
        latest_backup_schema_version=backup_schema,
        current_schema_version=EXPECTED_SCHEMA_VERSION,
        latest_completed_research_at=(
            None
            if latest_research is None
            else latest_research.isoformat()
            .replace("+00:00", "Z")
        ),
        completed_research_since_backup=completed_since,
        min_new_research_iterations=minimum_research,
        max_age_hours=maximum_age,
    )
