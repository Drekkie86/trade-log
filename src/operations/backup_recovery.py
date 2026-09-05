from __future__ import annotations

import sqlite3
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from src.database.repository import EXPECTED_SCHEMA_VERSION
from src.operations.sqlite_runtime import resolve_backup_dir


@dataclass(frozen=True)
class BackupInventoryEntry:
    path: str
    filename: str
    size_bytes: int
    modified_at: str
    age_hours: float
    schema_version: int | None
    integrity_check: str | None
    foreign_key_violation_count: int | None
    state: str
    detail: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class BackupInventory:
    directory: str
    total_files: int
    valid_files: int
    invalid_files: int
    latest_valid_path: str | None
    latest_valid_age_hours: float | None
    entries: tuple[BackupInventoryEntry, ...]

    def as_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["entries"] = [entry.as_dict() for entry in self.entries]
        return data


@dataclass(frozen=True)
class RestoreDrillResult:
    source_backup: str
    source_schema_version: int
    restored_schema_version: int
    integrity_check: str
    foreign_key_violation_count: int
    restored_size_bytes: int
    state: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _inspect_sqlite(path: Path) -> tuple[int | None, str | None, int | None, str, str]:
    try:
        uri = path.resolve().as_uri() + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=30.0)
    except sqlite3.Error as exc:
        return None, None, None, "INVALID", f"OPEN_FAILED:{type(exc).__name__}"

    try:
        try:
            row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
            version = None if not row or row[0] is None else int(row[0])
        except sqlite3.Error:
            version = None

        try:
            integrity = str(conn.execute("PRAGMA quick_check").fetchone()[0])
        except sqlite3.Error as exc:
            return version, None, None, "INVALID", f"QUICK_CHECK_FAILED:{type(exc).__name__}"

        try:
            fk_count = len(conn.execute("PRAGMA foreign_key_check").fetchall())
        except sqlite3.Error as exc:
            return version, integrity, None, "INVALID", f"FK_CHECK_FAILED:{type(exc).__name__}"
    finally:
        conn.close()

    if version != EXPECTED_SCHEMA_VERSION:
        return version, integrity, fk_count, "INVALID", "SCHEMA_VERSION_MISMATCH"
    if integrity != "ok":
        return version, integrity, fk_count, "INVALID", "INTEGRITY_CHECK_FAILED"
    if fk_count:
        return version, integrity, fk_count, "INVALID", "FOREIGN_KEY_VIOLATIONS"
    return version, integrity, fk_count, "VALID", "VERIFIED"


def inventory_backups(
    backup_dir: str | Path | None = None,
    *,
    now: datetime | None = None,
) -> BackupInventory:
    directory = resolve_backup_dir(backup_dir)
    observed_at = datetime.now(UTC) if now is None else now.astimezone(UTC)

    if not directory.exists():
        return BackupInventory(
            directory=str(directory), total_files=0, valid_files=0, invalid_files=0,
            latest_valid_path=None, latest_valid_age_hours=None, entries=(),
        )

    entries: list[BackupInventoryEntry] = []
    for path in sorted(directory.glob("christiania_backup_*.db"), reverse=True):
        stat = path.stat()
        modified = datetime.fromtimestamp(stat.st_mtime, tz=UTC)
        age_hours = max(0.0, (observed_at - modified).total_seconds() / 3600.0)
        version, integrity, fk_count, state, detail = _inspect_sqlite(path)
        entries.append(
            BackupInventoryEntry(
                path=str(path), filename=path.name, size_bytes=stat.st_size,
                modified_at=modified.isoformat(), age_hours=age_hours,
                schema_version=version, integrity_check=integrity,
                foreign_key_violation_count=fk_count, state=state, detail=detail,
            )
        )

    valid = [entry for entry in entries if entry.state == "VALID"]
    latest = min(valid, key=lambda entry: entry.age_hours) if valid else None
    return BackupInventory(
        directory=str(directory), total_files=len(entries), valid_files=len(valid),
        invalid_files=len(entries) - len(valid),
        latest_valid_path=None if latest is None else latest.path,
        latest_valid_age_hours=None if latest is None else latest.age_hours,
        entries=tuple(entries),
    )


def resolve_latest_valid_backup(backup_dir: str | Path | None = None) -> Path:
    inventory = inventory_backups(backup_dir)
    if not inventory.latest_valid_path:
        raise FileNotFoundError("No valid Christiania backup is available.")
    return Path(inventory.latest_valid_path)


def run_restore_drill(backup_path: str | Path) -> RestoreDrillResult:
    source = Path(backup_path).expanduser()
    if not source.is_file():
        raise FileNotFoundError(f"Backup not found: {source}")

    source_version, source_integrity, source_fk, state, detail = _inspect_sqlite(source)
    if state != "VALID" or source_version is None:
        raise RuntimeError(f"Backup is not valid for restore drill: {detail}")

    with tempfile.TemporaryDirectory(prefix="christiania_restore_drill_") as td:
        restored = Path(td) / "restored.db"
        source_uri = source.resolve().as_uri() + "?mode=ro"
        source_conn = sqlite3.connect(source_uri, uri=True, timeout=30.0)
        target_conn = sqlite3.connect(restored)
        try:
            source_conn.backup(target_conn)
            target_conn.commit()
        finally:
            target_conn.close()
            source_conn.close()

        restored_version, integrity, fk_count, restored_state, restored_detail = _inspect_sqlite(restored)
        if restored_state != "VALID" or restored_version is None:
            raise RuntimeError(f"Restored copy failed verification: {restored_detail}")
        restored_size = restored.stat().st_size

    return RestoreDrillResult(
        source_backup=str(source), source_schema_version=source_version,
        restored_schema_version=restored_version, integrity_check=str(integrity),
        foreign_key_violation_count=int(fk_count or 0), restored_size_bytes=restored_size,
        state="PASSED",
    )
