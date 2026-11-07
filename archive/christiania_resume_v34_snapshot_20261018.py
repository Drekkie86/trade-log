#!/usr/bin/env python3
"""Safely validate and promote a stopped VACUUM-INTO v34 recovery snapshot.

Production bridge only. Never copies, writes or migrates the live database,
never deletes previous recovery points, and never starts a normal backup.
Must be launched as a time-bounded, detached job after confirming the old
volume-v34 VACUUM job is inactive. This script will NOT run a new VACUUM.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time

import christiania_volume_v34_recovery_snapshot as bridge

PARTIAL_NAME = ".christiania_backup_20261017T203934Z.incomplete.db"
FINAL_NAME = "christiania_backup_20261017T203934Z.db"
MIN_EXPECTED_BYTES = 20 * 1024**3
SHA_LIMIT_SECONDS = 900
ROOT_RECOVERY = (
    Path("/var/lib/christiania/backups/christiania_backup_20261001T233013Z.db"),
    Path("/var/lib/christiania/backups/christiania_backup_20261008T233215Z.db"),
)
HISTORIC_VOLUME_ARCHIVE = "christiania_backup_20261008T233215Z.db.gz"


def _require_prior_recovery(backups: Path, *, production: bool) -> None:
    if not production:
        return
    for path in ROOT_RECOVERY:
        if not path.is_file() or path.is_symlink():
            raise RuntimeError(f"PRIOR_ROOT_RECOVERY_MISSING:{path.name}")
    seed = backups / HISTORIC_VOLUME_ARCHIVE
    if not seed.is_file() or not (backups / (seed.name + ".manifest.json")).is_file():
        raise RuntimeError("PRIOR_VOLUME_RECOVERY_MISSING")


def _sha256_bounded(path: Path, *, limit_seconds: int) -> str:
    start = time.monotonic()
    latest = start
    digest = hashlib.sha256()
    with path.open("rb") as fd:
        while True:
            now = time.monotonic()
            if now - start > limit_seconds:
                raise TimeoutError(f"RESUME_HASH_TIMEOUT:{limit_seconds}")
            chunk = fd.read(8 * 1024**2)
            if not chunk:
                break
            digest.update(chunk)
            if now - latest > 30:
                bridge.status(
                    "HASHING_RESUMED_SNAPSHOT",
                    elapsed_seconds=round(now - start),
                    source_file=path.name,
                )
                latest = now
    return digest.hexdigest()


def require_independent_volume(source: Path, volume: Path, backups: Path) -> None:
    if not volume.is_mount() or volume.is_symlink() or (
        os.stat(volume).st_dev == os.stat(source).st_dev
    ):
        raise RuntimeError("RECOVERY_VOLUME_NOT_INDEPENDENT_MOUNT")
    if not backups.is_dir() or backups.is_symlink() or not (
        backups.resolve(strict=True).is_relative_to(volume.resolve(strict=True))
    ):
        raise RuntimeError("INVALID_BACKUPS_PATH")


def resume_snapshot(
    *,
    source: Path,
    volume: Path,
    backups: Path,
    expected_schema: int = 34,
    partial_name: str = PARTIAL_NAME,
    final_name: str = FINAL_NAME,
    min_expected_bytes: int = MIN_EXPECTED_BYTES,
    production: bool = True,
    hash_limit_seconds: int = SHA_LIMIT_SECONDS,
) -> Path:
    if min_expected_bytes < 1 or hash_limit_seconds < 1:
        raise ValueError("Invalid minimum file size or hash time limit.")
    # Do not call the snapshot-specific free-space planner: no new database
    # copy is created. Instead prove mount independence and the reserve.
    if not source.is_file() or source.is_symlink():
        raise RuntimeError("LIVE_DB_MISSING_OR_SYMLINK")
    require_independent_volume(source, volume, backups)
    _require_prior_recovery(backups, production=production)
    with sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True) as live:
        version_row = live.execute("SELECT MAX(version) FROM schema_version").fetchone()
        if not version_row or int(version_row[0]) != expected_schema:
            raise RuntimeError("LIVE_SCHEMA_CHANGED_SINCE_SNAPSHOT")
    if partial_name != PARTIAL_NAME or final_name != FINAL_NAME:
        if production:
            raise RuntimeError("PRODUCTION_SNAPSHOT_FILENAME_MISMATCH")
    partial = backups / partial_name
    final = backups / final_name
    manifest = backups / (final_name + ".manifest.json")
    lock_path = backups / ".christiania_backup.lock"
    import fcntl
    with lock_path.open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        if any(p.exists() or p.is_symlink() for p in (final, manifest)):
            raise FileExistsError("RESUMED_BACKUP_ALREADY_PROMOTED")
        if not partial.is_file() or partial.is_symlink():
            raise RuntimeError("INCOMPLETE_SNAPSHOT_MISSING_OR_SYMLINK")
        before = partial.stat()
        if before.st_size < min_expected_bytes:
            raise RuntimeError("INCOMPLETE_SNAPSHOT_UNDERSIZED")
        time.sleep(2)
        after = partial.stat()
        if (after.st_size, after.st_mtime_ns, after.st_ino) != (
            before.st_size, before.st_mtime_ns, before.st_ino
        ):
            raise RuntimeError("INCOMPLETE_SNAPSHOT_IS_STILL_CHANGING")
        bridge.status("RESUMED_ROUTINE_VERIFICATION",
                      snapshot=str(partial), bytes=after.st_size,
                      verification_level="routine")
        schema, quick, fk = bridge.verify_sqlite(
            partial, expected_schema=expected_schema,
        )
        bridge.status("HASHING_RESUMED_SNAPSHOT",
                      schema_version=schema, snapshot_bytes=after.st_size)
        digest = _sha256_bounded(partial, limit_seconds=hash_limit_seconds)
        after_hash = partial.stat()
        if (after_hash.st_size, after_hash.st_mtime_ns, after_hash.st_ino) != (
            after.st_size, after.st_mtime_ns, after.st_ino
        ):
            raise RuntimeError("SNAPSHOT_CHANGED_DURING_HASH")
        payload = {
            "schema_version": schema,
            "verification_level": "routine",
            "quick_check": quick,
            "integrity_check": None,
            "foreign_key_violation_count": fk,
            "snapshot_method": "VACUUM_INTO",
            "snapshot_path": str(final),
            "source_path": str(source),
            "snapshot_bytes": after.st_size,
            "snapshot_sha256": digest,
            "resumed_from_stopped_snapshot": True,
            "created_at_utc": bridge.datetime.now(bridge.UTC).isoformat(),
        }
        staged_manifest = manifest.with_name("." + manifest.name + ".tmp")
        try:
            with staged_manifest.open("x", encoding="utf-8") as handle:
                json.dump(payload, handle, sort_keys=True, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            # No source or old recovery point is ever deleted. A failure
            # after the file rename rolls back to the incomplete filename.
            os.replace(partial, final)
            os.replace(staged_manifest, manifest)
            if hasattr(os, "O_DIRECTORY"):
                fd = os.open(backups, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
            bridge.status("COMPLETE", **payload)
        except BaseException:
            if final.is_file() and not manifest.is_file() and not partial.exists():
                os.replace(final, partial)
            if staged_manifest.exists():
                staged_manifest.unlink()
            raise
        return final


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if args.check_only == args.resume:
        parser.error("Select exactly one of --check-only or --resume.")
    if args.check_only:
        # Check preconditions without reading 30 GiB or modifying anything.
        volume = bridge.VOLUME
        source = bridge.SOURCE
        backups = bridge.BACKUP_DIR
        partial = backups / PARTIAL_NAME
        _require_prior_recovery(backups, production=True)
        if not volume.is_mount() or not partial.is_file():
            raise RuntimeError("RESUME_PREFLIGHT_MOUNT_OR_PARTIAL_MISSING")
        print(json.dumps({"eligible_for_verification": True,
                          "incomplete_snapshot": str(partial),
                          "bytes": partial.stat().st_size,
                          "requires_previous_unit_stopped": True}), flush=True)
        return 0
    try:
        resume_snapshot(
            source=bridge.SOURCE, volume=bridge.VOLUME, backups=bridge.BACKUP_DIR,
        )
    except BaseException as exc:
        bridge.status("FAILED_RESUME", error=f"{type(exc).__name__}:{str(exc)[:160]}")
        raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
