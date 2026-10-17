#!/usr/bin/env python3
"""One-off, fail-closed v34 live-recovery snapshot on a separate mounted volume.

Operational bridge only: production v34 code cannot be upgraded to repository
v36 before a fresh rollback. This script has no app import or schema migration.
Run as the christiania service user via a bounded, detached systemd unit.
Retains all existing recovery points; writes ONLY a new volume recovery file.
"""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import time

SOURCE = Path("/var/lib/christiania/data/trade_log.db")
VOLUME = Path("/mnt/HC_Volume_107172834")
BACKUP_DIR = VOLUME / "backups"
STATUS = BACKUP_DIR / "volume_v34_fresh_snapshot_status.json"
EXPECTED_SCHEMA = 34
SNAPSHOT_LIMIT_SECONDS = 1800
VERIFICATION_LIMIT_SECONDS = 900
RESERVE_BYTES = 15 * 1024**3


def stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def status(phase: str, **kw: object) -> None:
    record = {"phase": phase, "at_utc": datetime.now(UTC).isoformat(), **kw}
    print(json.dumps(record, sort_keys=True), flush=True)
    temp = STATUS.with_name("." + STATUS.name + ".tmp")
    with temp.open("x", encoding="utf-8") as fd:
        json.dump(record, fd, sort_keys=True, indent=2)
        fd.flush()
        os.fsync(fd.fileno())
    os.replace(temp, STATUS)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(16 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_storage(*, source: Path, volume: Path, output_dir: Path) -> int:
    if not source.is_file() or source.is_symlink():
        raise RuntimeError("SOURCE_DATABASE_MISSING_OR_SYMLINK")
    if not volume.is_mount() or volume.is_symlink() or os.stat(volume).st_dev == os.stat(source).st_dev:
        raise RuntimeError("RECOVERY_VOLUME_NOT_INDEPENDENT_MOUNT")
    if not output_dir.is_dir() or output_dir.is_symlink():
        raise RuntimeError("RECOVERY_BACKUP_DIRECTORY_NOT_PRESENT")
    if not output_dir.resolve(strict=True).is_relative_to(volume.resolve(strict=True)):
        raise RuntimeError("RECOVERY_BACKUP_DIRECTORY_ESCAPES_VOLUME")
    usage = shutil.disk_usage(volume)
    needed = source.stat().st_size + max(RESERVE_BYTES, int(usage.total * .15))
    if usage.free <= needed:
        raise RuntimeError(f"RECOVERY_HEADROOM_INSUFFICIENT free={usage.free} needed={needed}")
    return usage.free


def verify_sqlite(path: Path, *, expected_schema: int) -> tuple[int, str, int]:
    """Bounded routine verification, never represented as full integrity."""
    uri = path.resolve().as_uri() + "?mode=ro"
    started = time.monotonic()
    timed_out = [False]

    def progress() -> int:
        if time.monotonic() - started >= VERIFICATION_LIMIT_SECONDS:
            timed_out[0] = True
            return 1
        return 0

    conn = sqlite3.connect(uri, uri=True, timeout=30)
    try:
        conn.execute("PRAGMA query_only=ON")
        conn.set_progress_handler(progress, 10_000)
        version = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
        if int(version) != expected_schema:
            raise RuntimeError(f"WRONG_SNAPSHOT_SCHEMA:{version}")
        status("VERIFYING_QUICK_CHECK", schema_version=int(version),
               verification_level="routine")
        quick = str(conn.execute("PRAGMA quick_check(1)").fetchone()[0])
        if quick != "ok":
            raise RuntimeError(f"FAILED_QUICK_CHECK:{quick}")
        status("VERIFYING_FOREIGN_KEYS", quick_check=quick,
               integrity_check=None, verification_level="routine")
        fk_count = 1 if conn.execute("PRAGMA foreign_key_check").fetchone() else 0
        if fk_count:
            raise RuntimeError("FAILED_FOREIGN_KEY_CHECK")
    except sqlite3.OperationalError as exc:
        if timed_out[0]:
            raise TimeoutError("ROUTINE_VERIFICATION_TIMEOUT") from exc
        raise
    finally:
        conn.set_progress_handler(None, 0)
        conn.close()
    return expected_schema, quick, 0


def take_snapshot(*, source: Path, volume: Path, output_dir: Path,
                  expected_schema: int, prefix: str, max_seconds: int) -> Path:
    if max_seconds < 1:
        raise ValueError("SNAPSHOT_TIMEOUT_MUST_BE_POSITIVE")
    free = require_storage(source=source, volume=volume, output_dir=output_dir)
    run_id = stamp()
    final = output_dir / f"{prefix}_{run_id}.db"
    partial = output_dir / f".{prefix}_{run_id}.incomplete.db"
    manifest = final.with_name(final.name + ".manifest.json")
    if any(p.exists() or p.is_symlink() for p in (final, partial, manifest)):
        raise RuntimeError("SNAPSHOT_FILENAME_COLLISION")
    # Lock only this operational recovery process, never the source DB.
    import fcntl
    lock_path = output_dir / f".{prefix}.lock"
    with lock_path.open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        started = time.monotonic()
        latest_progress = [started]
        exceeded = [False]

        def on_progress() -> int:
            now = time.monotonic()
            if now - started >= max_seconds:
                exceeded[0] = True
                return 1
            if now - latest_progress[0] > 30:
                status("SNAPSHOTTING", elapsed_seconds=int(now - started),
                       source_bytes=source.stat().st_size)
                latest_progress[0] = now
            return 0

        try:
            status("SNAPSHOTTING", source=str(source), output=str(partial),
                   source_bytes=source.stat().st_size,
                   initial_free_bytes=free, max_seconds=max_seconds)
            uri = source.resolve().as_uri() + "?mode=ro"
            conn = sqlite3.connect(uri, uri=True, timeout=30)
            try:
                v = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
                if int(v) != expected_schema:
                    raise RuntimeError(f"WRONG_LIVE_SCHEMA:{v}")
                conn.set_progress_handler(on_progress, 10_000)
                try:
                    conn.execute("VACUUM main INTO ?", (str(partial),))
                except sqlite3.OperationalError as exc:
                    if exceeded[0]:
                        raise TimeoutError(f"SNAPSHOT_TIMEOUT:{max_seconds}s") from exc
                    raise
                finally:
                    conn.set_progress_handler(None, 0)
            finally:
                conn.close()
            if partial.stat().st_size <= 0:
                raise RuntimeError("EMPTY_SNAPSHOT")
            os.chmod(partial, 0o600)
            with partial.open("r+b") as handle:
                os.fsync(handle.fileno())
            status("COPY_DONE", snapshot_bytes=partial.stat().st_size)
            schema, quick, fk = verify_sqlite(partial, expected_schema=expected_schema)
            status("HASHING", snapshot_bytes=partial.stat().st_size)
            digest = sha256(partial)
            os.replace(partial, final)
            if hasattr(os, "O_DIRECTORY"):
                dirfd = os.open(final.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(dirfd)
                finally:
                    os.close(dirfd)
            manifest_data = {
                "schema_version": schema, "verification_level": "routine",
                "quick_check": quick, "integrity_check": None,
                "foreign_key_violation_count": fk, "snapshot_method": "VACUUM_INTO",
                "source_path": str(source), "snapshot_path": str(final),
                "snapshot_bytes": final.stat().st_size,
                "snapshot_sha256": digest,
                "created_at_utc": datetime.now(UTC).isoformat(),
            }
            temporary_manifest = manifest.with_name("." + manifest.name + ".tmp")
            with temporary_manifest.open("x", encoding="utf-8") as file:
                json.dump(manifest_data, file, indent=2, sort_keys=True)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary_manifest, manifest)
            status("COMPLETE", **manifest_data)
            return final
        except BaseException as exc:
            status("FAILED", error=f"{type(exc).__name__}:{str(exc)[:200]}")
            if partial.exists() and not partial.is_symlink():
                partial.unlink()
            raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default=str(SOURCE))
    parser.add_argument("--volume", default=str(VOLUME))
    parser.add_argument("--backups", default=str(BACKUP_DIR))
    parser.add_argument("--expected-schema", type=int, default=EXPECTED_SCHEMA)
    parser.add_argument("--max-seconds", type=int, default=SNAPSHOT_LIMIT_SECONDS)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    source, volume, backups = Path(args.source), Path(args.volume), Path(args.backups)
    free = require_storage(source=source, volume=volume, output_dir=backups)
    if args.check_only:
        with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as c:
            version = c.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
        if int(version) != args.expected_schema:
            raise RuntimeError(f"WRONG_LIVE_SCHEMA:{version}")
        print(json.dumps({"ready": True, "schema_version": version,
                          "free_bytes": free}), flush=True)
        return 0
    take_snapshot(source=source, volume=volume, output_dir=backups,
                  expected_schema=args.expected_schema,
                  prefix="christiania_backup",
                  max_seconds=args.max_seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
