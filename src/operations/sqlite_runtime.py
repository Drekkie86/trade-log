from __future__ import annotations

import os
import sqlite3
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from src.config import get_runtime_setting
from src.database.repository import (
    EXPECTED_SCHEMA_VERSION,
    resolve_db_path,
)


DEFAULT_BACKUP_RETENTION = 14


@dataclass(frozen=True)
class DatabaseHealth:
    path: str
    exists: bool
    size_bytes: int | None
    schema_version: int | None
    expected_schema_version: int
    journal_mode: str | None
    busy_timeout_ms: int | None
    quick_check: str | None
    foreign_key_violation_count: int | None

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class BackupResult:
    source_path: str
    backup_path: str
    schema_version: int
    integrity_check: str
    foreign_key_violation_count: int
    pruned_count: int

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def resolve_backup_dir(
    backup_dir: str | Path | None = None,
) -> Path:
    if backup_dir is not None:
        return Path(backup_dir).expanduser()

    configured = get_runtime_setting(
        "CHRISTIANIA_BACKUP_DIR"
    )

    if configured:
        return Path(configured).expanduser()

    return (
        Path(__file__).resolve().parents[2]
        / "backups"
    )


def backup_retention_count() -> int:
    configured = get_runtime_setting(
        "CHRISTIANIA_BACKUP_RETENTION"
    )

    if configured is None:
        return DEFAULT_BACKUP_RETENTION

    value = int(configured)

    if value < 1:
        raise ValueError(
            "CHRISTIANIA_BACKUP_RETENTION must be >= 1."
        )

    return value


def open_readonly_connection(
    db_path: str | Path | None = None,
) -> sqlite3.Connection:
    path = resolve_db_path(db_path)

    if not path.exists():
        raise FileNotFoundError(
            f"Christiania database not found: {path}"
        )

    uri = path.resolve().as_uri() + "?mode=ro"

    connection = sqlite3.connect(
        uri,
        uri=True,
        timeout=30.0,
    )
    connection.row_factory = sqlite3.Row
    connection.execute(
        "PRAGMA query_only = ON;"
    )
    connection.execute(
        "PRAGMA foreign_keys = ON;"
    )
    connection.execute(
        "PRAGMA busy_timeout = 30000;"
    )

    return connection


def inspect_database(
    db_path: str | Path | None = None,
) -> DatabaseHealth:
    path = resolve_db_path(db_path)

    if not path.exists():
        return DatabaseHealth(
            path=str(path),
            exists=False,
            size_bytes=None,
            schema_version=None,
            expected_schema_version=EXPECTED_SCHEMA_VERSION,
            journal_mode=None,
            busy_timeout_ms=None,
            quick_check=None,
            foreign_key_violation_count=None,
        )

    conn = open_readonly_connection(path)

    try:
        schema_row = conn.execute(
            '''
            SELECT MAX(version)
            FROM schema_version;
            '''
        ).fetchone()

        schema_version = (
            int(schema_row[0])
            if schema_row
            and schema_row[0] is not None
            else None
        )

        journal_mode = str(
            conn.execute(
                "PRAGMA journal_mode;"
            ).fetchone()[0]
        ).lower()

        busy_timeout_ms = int(
            conn.execute(
                "PRAGMA busy_timeout;"
            ).fetchone()[0]
        )

        quick_check = str(
            conn.execute(
                "PRAGMA quick_check;"
            ).fetchone()[0]
        )

        fk_count = len(
            conn.execute(
                "PRAGMA foreign_key_check;"
            ).fetchall()
        )

    finally:
        conn.close()

    return DatabaseHealth(
        path=str(path),
        exists=True,
        size_bytes=path.stat().st_size,
        schema_version=schema_version,
        expected_schema_version=EXPECTED_SCHEMA_VERSION,
        journal_mode=journal_mode,
        busy_timeout_ms=busy_timeout_ms,
        quick_check=quick_check,
        foreign_key_violation_count=fk_count,
    )


def _verify_backup(path: Path) -> tuple[int, str, int]:
    conn = sqlite3.connect(path)

    try:
        version_row = conn.execute(
            '''
            SELECT MAX(version)
            FROM schema_version;
            '''
        ).fetchone()

        if (
            version_row is None
            or version_row[0] is None
        ):
            raise RuntimeError(
                "Backup contains no schema version."
            )

        version = int(version_row[0])

        integrity = str(
            conn.execute(
                "PRAGMA integrity_check;"
            ).fetchone()[0]
        )

        fk_rows = conn.execute(
            "PRAGMA foreign_key_check;"
        ).fetchall()

    finally:
        conn.close()

    if integrity != "ok":
        raise RuntimeError(
            f"Backup integrity_check failed: {integrity}"
        )

    if fk_rows:
        raise RuntimeError(
            "Backup foreign_key_check returned violations."
        )

    return version, integrity, len(fk_rows)


def _prune_backups(
    directory: Path,
    *,
    keep: int,
) -> int:
    backups = sorted(
        directory.glob(
            "christiania_backup_*.db"
        ),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    pruned = 0

    for stale in backups[keep:]:
        stale.unlink()
        pruned += 1

    return pruned


def create_verified_backup(
    *,
    db_path: str | Path | None = None,
    backup_dir: str | Path | None = None,
    retention: int | None = None,
) -> BackupResult:
    source = resolve_db_path(db_path)

    if not source.exists():
        raise FileNotFoundError(
            f"Christiania database not found: {source}"
        )

    target_dir = resolve_backup_dir(
        backup_dir
    )
    target_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    keep = (
        retention
        if retention is not None
        else backup_retention_count()
    )

    if keep < 1:
        raise ValueError(
            "Backup retention must be >= 1."
        )

    stamp = datetime.now(
        UTC
    ).strftime("%Y%m%dT%H%M%SZ")

    final_path = (
        target_dir
        / f"christiania_backup_{stamp}.db"
    )
    temp_path = (
        target_dir
        / f".christiania_backup_{stamp}.tmp.db"
    )

    if final_path.exists() or temp_path.exists():
        raise FileExistsError(
            "Backup timestamp collision."
        )

    source_uri = source.resolve().as_uri() + "?mode=ro"

    source_conn = sqlite3.connect(
        source_uri,
        uri=True,
        timeout=30.0,
    )
    target_conn = sqlite3.connect(
        temp_path
    )

    try:
        source_conn.backup(
            target_conn
        )
        target_conn.commit()
    finally:
        target_conn.close()
        source_conn.close()

    try:
        version, integrity, fk_count = (
            _verify_backup(temp_path)
        )

        if version != EXPECTED_SCHEMA_VERSION:
            raise RuntimeError(
                f"Backup schema v{version} does not match "
                f"expected v{EXPECTED_SCHEMA_VERSION}."
            )

        os.replace(
            temp_path,
            final_path,
        )

    except Exception:
        if temp_path.exists():
            temp_path.unlink()
        raise

    pruned = _prune_backups(
        target_dir,
        keep=keep,
    )

    return BackupResult(
        source_path=str(source),
        backup_path=str(final_path),
        schema_version=version,
        integrity_check=integrity,
        foreign_key_violation_count=fk_count,
        pruned_count=pruned,
    )
