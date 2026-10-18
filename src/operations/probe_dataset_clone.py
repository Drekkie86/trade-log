"""Release-probe dataset: disposable, mounted, schema-migrated live snapshot.

Only the scratch SQLite copy is writable. The production source is opened
in immutable-role READ ONLY mode for the SQLite online-backup API; no release
migrations, backups or release pointers ever touch production here.
"""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import time

from src.config import get_runtime_setting, load_runtime_env_file
from src.database.migration_runner import apply_pending_migrations, get_schema_version
from src.database.repository import EXPECTED_SCHEMA_VERSION, resolve_db_path
from src.operations.migration_delta_checks import (
    capture_migration_schema, verify_additive_schema_migration,
)

RESERVE_MIN_BYTES = 15 * 1024**3
RESERVE_FRACTION = 0.15


def _log(stage: str) -> None:
    print(f"PERFORMANCE_DATASET_{stage}: {datetime.now(UTC).isoformat()}", file=sys.stderr, flush=True)


def _mounted_volume_is_separate(volume: Path, source: Path) -> bool:
    return (
        volume.is_absolute() and not volume.is_symlink()
        and volume.is_mount()
        and os.stat(volume).st_dev != os.stat(source).st_dev
    )


def prepare_probe_dataset(
    *, source: Path, target: Path, provenance: Path, migrations_dir: Path,
    volume: Path, expected_version: int = EXPECTED_SCHEMA_VERSION,
) -> Path:
    source = source.expanduser().resolve(strict=True)
    target = target.expanduser()
    provenance = provenance.expanduser()
    volume = volume.expanduser()
    if not _mounted_volume_is_separate(volume, source):
        raise RuntimeError("PERFORMANCE_DATASET_VOLUME_NOT_SEPARATELY_MOUNTED")
    root = volume.resolve(strict=True)
    scratch = (root / "scratch")
    if not scratch.is_dir() or scratch.is_symlink():
        raise RuntimeError("PERFORMANCE_DATASET_SCRATCH_MISSING")
    if not target.is_absolute() or not provenance.is_absolute():
        raise RuntimeError("PERFORMANCE_DATASET_PATH_MUST_BE_ABSOLUTE")
    for path in (target, provenance):
        if path.exists() or path.is_symlink():
            raise RuntimeError("PERFORMANCE_DATASET_TARGET_EXISTS")
        if not path.parent.is_dir() or not path.parent.resolve().is_relative_to(scratch):
            raise RuntimeError("PERFORMANCE_DATASET_PATH_ESCAPES_SCRATCH")
    if target == provenance or not migrations_dir.is_dir():
        raise RuntimeError("PERFORMANCE_DATASET_INVALID_DESTINATION_OR_MIGRATIONS")

    with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True, timeout=60) as original:
        # mode=ro prevents source mutations. PRAGMA query_only would also
        # prohibit VACUUM INTO even though it only writes the scratch output.
        from_version = get_schema_version(original)
        if from_version > expected_version:
            raise RuntimeError("PERFORMANCE_DATASET_SOURCE_SCHEMA_NEWER_THAN_RELEASE")

        migrated = from_version != expected_version
        if migrated:
            size = source.stat().st_size
            usage = shutil.disk_usage(root)
            reserve = max(RESERVE_MIN_BYTES, int(usage.total * RESERVE_FRACTION))
            if usage.free <= size + reserve:
                raise RuntimeError(
                    f"PERFORMANCE_DATASET_NO_HEADROOM:free={usage.free} "
                    f"required={size + reserve}"
                )
            _log(f"COPY_BEGIN_V{from_version}_TO_V{expected_version}")
            # Refuse to follow a pre-existing symlink. SQLite opens the file
            # created exclusively with service-user-only permissions.
            fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(fd)
            # Incremental sqlite3.backup restarts when concurrent daemon
            # writes land during a multi-minute copy; its reported progress can
            # loop indefinitely. VACUUM INTO takes one consistent read snapshot,
            # exactly as the verified production backup path does. The source
            # remains opened with mode=ro and only this isolated target is written.
            _log("VACUUM_INTO_BEGIN")
            started = time.monotonic()
            last_log = [started]
            timed_out = [False]

            def vacuum_progress() -> int:
                now = time.monotonic()
                elapsed = now - started
                if elapsed >= 1800:
                    timed_out[0] = True
                    return 1
                if now - last_log[0] >= 120:
                    _log(f"COPY_PROGRESS_VACUUM_ELAPSED_{int(elapsed)}S")
                    last_log[0] = now
                return 0

            original.set_progress_handler(vacuum_progress, 10_000)
            try:
                original.execute("VACUUM main INTO ?", (str(target),))
            except sqlite3.OperationalError as exc:
                if timed_out[0]:
                    raise RuntimeError(
                        "PERFORMANCE_DATASET_SNAPSHOT_TIMEOUT_1800S"
                    ) from exc
                raise
            finally:
                original.set_progress_handler(None, 0)

            _log("COPY_COMPLETE_MIGRATING")
            target_conn = sqlite3.connect(target, timeout=90)
            try:
                target_conn.execute("PRAGMA foreign_keys=ON")
                schema_before = capture_migration_schema(target_conn)
                to_version = apply_pending_migrations(target_conn, migrations_dir)
                if to_version != expected_version:
                    raise RuntimeError("PERFORMANCE_DATASET_MIGRATION_NOT_AT_RELEASE_VERSION")
                _log("MIGRATED_VERIFYING_ADDITIVE_DELTA")
                delta = verify_additive_schema_migration(target_conn, schema_before)
                _log("MIGRATED_DELTA_VERIFIED_" + "_".join(delta.new_tables))
            finally:
                target_conn.close()
            measured_path = target
        else:
            measured_path = source

    payload = {
        "kind": "disposable_live_sqlite_snapshot" if migrated else "live_schema_matched",
        "production_source_path": str(source),
        "production_source_bytes_at_start": source.stat().st_size,
        "measured_database_path": str(measured_path),
        "source_schema_version": from_version,
        "measured_schema_version": expected_version,
        "disposable_migration": migrated,
        "volume_mountpoint": str(root) if migrated else None,
        "created_at_utc": datetime.now(UTC).isoformat(),
    }
    tmp = provenance.with_name("." + provenance.name + ".tmp")
    with tmp.open("x", encoding="utf-8") as out:
        json.dump(payload, out, sort_keys=True, indent=2)
        out.flush()
        os.fsync(out.fileno())
    os.replace(tmp, provenance)
    _log("READY")
    return measured_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--provenance", required=True)
    parser.add_argument("--migrations-dir", required=True)
    args = parser.parse_args()
    if not load_runtime_env_file(args.env_file, overwrite=False):
        raise RuntimeError("PERFORMANCE_DATASET_ENV_UNAVAILABLE")
    mount = get_runtime_setting("CHRISTIANIA_RECOVERY_VOLUME_MOUNTPOINT")
    if not mount:
        raise RuntimeError("PERFORMANCE_DATASET_VOLUME_NOT_CONFIGURED")
    source = resolve_db_path()
    path = prepare_probe_dataset(
        source=source, target=Path(args.target), provenance=Path(args.provenance),
        migrations_dir=Path(args.migrations_dir), volume=Path(mount),
    )
    print(str(path), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
