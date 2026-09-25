from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, Thread
from time import monotonic
from typing import Iterator

from src.config import load_runtime_env_file
from src.database.migration_runner import apply_pending_migrations, get_schema_version
from src.database.repository import EXPECTED_SCHEMA_VERSION, resolve_db_path
from src.operations.sqlite_runtime import (
    assert_backup_capacity,
    backup_logical_source_bytes,
    inspect_database,
    resolve_backup_dir,
)


HEARTBEAT_INTERVAL_SECONDS = 15.0
DEFAULT_RELEASE_ROLLBACK_RETENTION = 3


@dataclass(frozen=True)
class ReleaseDatabaseResult:
    database_path: str
    backup_path: str
    schema_before: int
    schema_after: int
    migrated: bool

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _progress(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


@contextmanager
def _heartbeat(label: str) -> Iterator[None]:
    started = monotonic()
    stopped = Event()
    succeeded = False

    def emit() -> None:
        while not stopped.wait(HEARTBEAT_INTERVAL_SECONDS):
            elapsed = int(monotonic() - started)
            _progress(f"{label}: still running; elapsed={elapsed}s")

    _progress(f"{label}: started.")
    thread = Thread(
        target=emit,
        name="christiania-release-db-progress",
        daemon=True,
    )
    thread.start()
    try:
        yield
        succeeded = True
    finally:
        stopped.set()
        thread.join(timeout=1.0)
        elapsed = monotonic() - started
        outcome = "completed" if succeeded else "stopped"
        _progress(f"{label}: {outcome} after {elapsed:.1f}s.")


def _fsync_directory(path: Path) -> None:
    """Persist a directory-entry update on POSIX after an atomic rename."""
    if os.name == "nt":
        return

    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    directory_fd = os.open(path, flags)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _verify_database(path: Path, *, expected_version: int) -> None:
    health = inspect_database(path)
    if not health.exists:
        raise RuntimeError(f"Christiania database is missing: {path}")
    if health.schema_version != expected_version:
        raise RuntimeError(
            f"Database schema v{health.schema_version} does not match expected "
            f"v{expected_version}."
        )
    if health.journal_mode != "wal":
        raise RuntimeError(f"Database is not in WAL mode: {health.journal_mode}")
    if health.quick_check != "ok":
        raise RuntimeError(f"Database quick_check failed: {health.quick_check}")
    if health.foreign_key_violation_count != 0:
        raise RuntimeError(
            "Database foreign_key_check returned "
            f"{health.foreign_key_violation_count} violation(s)."
        )


def _verify_sqlite_copy(path: Path, *, expected_version: int) -> None:
    uri = path.resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=30.0)
    try:
        version = get_schema_version(conn)
        integrity = str(conn.execute("PRAGMA integrity_check;").fetchone()[0])
        fk_count = len(conn.execute("PRAGMA foreign_key_check;").fetchall())
    finally:
        conn.close()

    if version != expected_version:
        raise RuntimeError(
            f"Rollback backup schema v{version} does not match source "
            f"schema v{expected_version}."
        )
    if integrity != "ok":
        raise RuntimeError(f"Rollback backup integrity_check failed: {integrity}")
    if fk_count:
        raise RuntimeError(
            f"Rollback backup has {fk_count} foreign-key violation(s)."
        )


def _prune_release_rollback_backups(
    backup_dir: Path,
    *,
    keep: int = DEFAULT_RELEASE_ROLLBACK_RETENTION,
) -> int:
    if keep < 1:
        raise ValueError("Release rollback retention must be >= 1.")

    backups = sorted(
        backup_dir.glob("christiania_release_rollback_*.db"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    pruned = 0
    for stale in backups[keep:]:
        stale.unlink()
        pruned += 1
    return pruned


def _create_rollback_backup(database: Path, backup_dir: Path, *, schema_version: int) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)

    # Capacity must be checked against the space that will actually exist when
    # the next rollback copy is created. Keeping all three historical rollback
    # snapshots until after the copy can deadlock deployment once the database
    # grows: the new copy cannot fit even though the oldest snapshot is already
    # outside the intended post-create retention window. Preserve two existing
    # generations, then let the newly verified snapshot become the third.
    preprune_keep = max(
        1,
        DEFAULT_RELEASE_ROLLBACK_RETENTION - 1,
    )
    prepruned = _prune_release_rollback_backups(
        backup_dir,
        keep=preprune_keep,
    )
    if prepruned:
        _progress(
            "Database preparation: pre-pruned "
            f"{prepruned} stale release rollback backup(s) "
            "before capacity check."
        )

    assert_backup_capacity(
        source=database,
        target_dir=backup_dir,
    )

    _progress(
        "Database preparation: rollback capacity PASS; "
        f"logical_source_bytes={backup_logical_source_bytes(database)}"
    )
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    final_path = backup_dir / (
        f"christiania_release_rollback_{stamp}_v{schema_version}.db"
    )
    temp_path = final_path.with_suffix(".tmp.db")
    if final_path.exists() or temp_path.exists():
        raise FileExistsError("Release rollback backup timestamp collision.")

    source_uri = database.resolve().as_uri() + "?mode=ro"
    source = sqlite3.connect(source_uri, uri=True, timeout=30.0)
    target = sqlite3.connect(temp_path, timeout=30.0)
    try:
        source.backup(target)
        target.commit()
    finally:
        target.close()
        source.close()

    try:
        _verify_sqlite_copy(temp_path, expected_version=schema_version)
        # Windows' os.fsync/_commit rejects a read-only descriptor; open the
        # already-written backup read/write so the durability barrier works on
        # both CI Windows and the production POSIX host.
        with temp_path.open("r+b") as handle:
            os.fsync(handle.fileno())
        os.replace(temp_path, final_path)
        _fsync_directory(backup_dir)
    except BaseException:
        if temp_path.exists():
            temp_path.unlink()
        raise

    try:
        pruned = _prune_release_rollback_backups(backup_dir)
        if pruned:
            _progress(
                f"Database preparation: pruned {pruned} stale release rollback backup(s)."
            )
    except OSError as exc:
        _progress(
            "Database preparation: warning: could not prune stale release rollback "
            f"backup(s): {exc}"
        )

    return final_path


def _write_rollback_pointer(path: Path, *, schema_version: int, backup: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    payload = f"{schema_version}\t{backup}\n"
    try:
        with temp.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
        _fsync_directory(path.parent)
    finally:
        if temp.exists():
            temp.unlink()


def restore_backup(*, database: Path, backup: Path, expected_version: int | None = None) -> int:
    if not backup.is_file():
        raise FileNotFoundError(f"Rollback backup not found: {backup}")

    with _heartbeat("Database rollback: verifying and restoring backup"):
        source_uri = backup.resolve().as_uri() + "?mode=ro"
        source = sqlite3.connect(source_uri, uri=True, timeout=30.0)
        target = sqlite3.connect(database, timeout=30.0)
        try:
            backup_version = get_schema_version(source)
            if expected_version is not None and backup_version != expected_version:
                raise RuntimeError(
                    f"Rollback backup schema v{backup_version} does not match "
                    f"required v{expected_version}."
                )
            integrity = str(source.execute("PRAGMA integrity_check;").fetchone()[0])
            fk_count = len(source.execute("PRAGMA foreign_key_check;").fetchall())
            if integrity != "ok" or fk_count:
                raise RuntimeError("Rollback backup failed integrity verification.")

            target.execute("PRAGMA wal_checkpoint(TRUNCATE);")
            source.backup(target)
            target.commit()
            target.execute("PRAGMA journal_mode = WAL;")
            target.commit()
        finally:
            target.close()
            source.close()

        _verify_database(database, expected_version=backup_version)
    return backup_version


def prepare_release_database(
    *,
    migrations_dir: Path,
    rollback_pointer: Path | None = None,
) -> ReleaseDatabaseResult:
    database = resolve_db_path()
    backup_dir = resolve_backup_dir()

    _progress("Database preparation: validating current schema and WAL metadata.")
    health = inspect_database(database, deep_integrity=False)
    if not health.exists or health.schema_version is None:
        raise RuntimeError("Persistent Christiania database is missing or unversioned.")
    if health.schema_version > EXPECTED_SCHEMA_VERSION:
        raise RuntimeError(
            f"Database schema v{health.schema_version} is newer than release "
            f"schema v{EXPECTED_SCHEMA_VERSION}."
        )
    if health.journal_mode != "wal":
        raise RuntimeError("Database must be in WAL mode before release migration.")

    schema_before = int(health.schema_version)

    if schema_before == EXPECTED_SCHEMA_VERSION:
        _progress(
            "Database preparation: no schema migration required; skipping rollback "
            "snapshot and deep database scans."
        )
        return ReleaseDatabaseResult(
            database_path=str(database),
            backup_path="",
            schema_before=schema_before,
            schema_after=EXPECTED_SCHEMA_VERSION,
            migrated=False,
        )

    with _heartbeat(
        "Database preparation: creating and fully verifying rollback backup"
    ):
        backup = _create_rollback_backup(
            database,
            backup_dir,
            schema_version=schema_before,
        )

    if rollback_pointer is not None:
        _write_rollback_pointer(
            rollback_pointer,
            schema_version=schema_before,
            backup=backup,
        )
        _progress("Database preparation: rollback pointer committed; migration may now begin.")
    else:
        _progress("Database preparation: verified rollback backup committed; migration may now begin.")

    try:
        with _heartbeat("Database preparation: applying pending migrations"):
            connection = sqlite3.connect(database, timeout=30.0)
            try:
                connection.execute("PRAGMA foreign_keys = ON;")
                after = apply_pending_migrations(connection, migrations_dir)
            finally:
                connection.close()

        if after != EXPECTED_SCHEMA_VERSION:
            raise RuntimeError(
                f"Release migrations ended at schema v{after}; expected "
                f"v{EXPECTED_SCHEMA_VERSION}."
            )

        with _heartbeat(
            "Database preparation: verifying migrated database integrity"
        ):
            _verify_database(database, expected_version=EXPECTED_SCHEMA_VERSION)
    except BaseException:
        _progress("Database preparation failed or was interrupted; restoring rollback backup.")
        restore_backup(
            database=database,
            backup=backup,
            expected_version=schema_before,
        )
        raise

    _progress("Database preparation complete.")
    return ReleaseDatabaseResult(
        database_path=str(database),
        backup_path=str(backup),
        schema_before=schema_before,
        schema_after=EXPECTED_SCHEMA_VERSION,
        migrated=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prepare or roll back Christiania's persistent database for a release."
    )
    parser.add_argument("--env-file", required=True)
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--migrations-dir", required=True)
    prepare.add_argument("--rollback-pointer", default=None)
    prepare.add_argument("--json", action="store_true")

    restore = subparsers.add_parser("restore")
    restore.add_argument("--backup", required=True)
    restore.add_argument("--expected-version", type=int, default=None)

    args = parser.parse_args()
    if not load_runtime_env_file(args.env_file, overwrite=False):
        raise SystemExit(f"Environment file missing or empty: {args.env_file}")

    if args.command == "prepare":
        result = prepare_release_database(
            migrations_dir=Path(args.migrations_dir).expanduser(),
            rollback_pointer=(
                None
                if args.rollback_pointer is None
                else Path(args.rollback_pointer).expanduser()
            ),
        )
        if args.json:
            print(json.dumps(result.as_dict(), sort_keys=True))
        else:
            print(
                f"Database prepared: v{result.schema_before} -> "
                f"v{result.schema_after}; rollback={result.backup_path}"
            )
        return 0

    database = resolve_db_path()
    version = restore_backup(
        database=database,
        backup=Path(args.backup).expanduser(),
        expected_version=args.expected_version,
    )
    print(f"Database restored to schema v{version} from {args.backup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
