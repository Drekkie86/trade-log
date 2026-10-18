#!/usr/bin/env python3
"""One-time, fail-closed archiving and restore rehearsal of completed 2026-10-17 v34 VACUUM.

This certifies archive-byte integrity and structural SQLite readability, NOT PRAGMA
quick_check/integrity_check across the database or a complete foreign-key audit.
Prior independent deep-verified recovery points must exist and are never touched.
"""
from __future__ import annotations

import fcntl
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import time
from datetime import UTC, datetime

VOLUME = Path("/mnt/HC_Volume_107172834")
BACKUPS = VOLUME / "backups"
LIVE = Path("/var/lib/christiania/data/trade_log.db")
PARTIAL = BACKUPS / ".christiania_backup_20261017T203934Z.incomplete.db"
ARCHIVE = BACKUPS / "christiania_backup_20261017T203934Z.db.gz"
MANIFEST = BACKUPS / (ARCHIVE.name + ".manifest.json")
STATUS = BACKUPS / "volume_v34_archive_recovery_status.json"
OLD_ROOT = Path("/var/lib/christiania/backups/christiania_backup_20261008T233215Z.db")
OLD_GZIP = BACKUPS / "christiania_backup_20261008T233215Z.db.gz"
LOCK = BACKUPS / ".christiania_v34_archive_recovery.lock"
RESERVE_BYTES = 15 * 1024**3
CHUNK = 8 * 1024**2
JOB_LIMIT_SECONDS = 5400
_started = time.monotonic()
_last_report = _started


def fsync_parent(p: Path) -> None:
    fd = os.open(p.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def report(phase: str, **fields: object) -> None:
    data = {"phase": phase, "at_utc": datetime.now(UTC).isoformat(), **fields}
    print(json.dumps(data, sort_keys=True), flush=True)
    tmp = STATUS.with_name("." + STATUS.name + ".tmp")
    with tmp.open("w", encoding="utf8") as f:
        os.chmod(tmp, 0o640)
        json.dump(data, f, sort_keys=True, indent=2)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, STATUS)


def tick(phase: str, count: int = 0) -> None:
    global _last_report
    now = time.monotonic()
    if now - _started > JOB_LIMIT_SECONDS:
        raise TimeoutError("ARCHIVE_RESTORE_JOB_DEADLINE")
    if now - _last_report > 30:
        report(phase, processed_bytes=count, elapsed_seconds=int(now-_started))
        _last_report = now


def check_file(p: Path, min_bytes: int = 1) -> None:
    if p.is_symlink() or not p.is_file() or p.stat().st_size < min_bytes:
        raise RuntimeError("UNSAFE_OR_MISSING_FILE:" + p.name)


def structural_check(p: Path) -> dict[str, object]:
    """Bounded metadata/open/read smoke. It cannot prove all SQLite pages valid."""
    check_file(p)
    if p.stat().st_size % 4096 != 0:
        raise RuntimeError("SQLITE_SIZE_NOT_PAGE_ALIGNED:" + p.name)
    with p.open("rb") as f:
        if f.read(16) != b"SQLite format 3\x00":
            raise RuntimeError("SQLITE_HEADER_INVALID:" + p.name)
    conn = sqlite3.connect(p.resolve().as_uri() + "?mode=ro&immutable=1", uri=True, timeout=5)
    try:
        conn.execute("PRAGMA query_only=ON")
        pages = int(conn.execute("PRAGMA page_count").fetchone()[0])
        page_size = int(conn.execute("PRAGMA page_size").fetchone()[0])
        version = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
        tables = int(conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0])
        if version != 34 or pages * page_size != p.stat().st_size or tables < 5:
            raise RuntimeError("STRUCTURAL_SCHEMA_SIZE_INVALID")
        return {"schema_version": version, "page_count": pages, "page_size": page_size, "table_count": tables}
    finally:
        conn.close()


def preflight() -> tuple[os.stat_result, dict[str, object]]:
    if not VOLUME.is_mount() or VOLUME.is_symlink():
        raise RuntimeError("NOT_INDEPENDENT_VOLUME")
    if os.stat(VOLUME).st_dev == os.stat(LIVE).st_dev:
        raise RuntimeError("NOT_DIFFERENT_FILESYSTEM")
    if not BACKUPS.is_dir() or BACKUPS.is_symlink():
        raise RuntimeError("BACKUP_DIR_NOT_SAFE")
    check_file(LIVE, 20 * 1024**3)
    check_file(PARTIAL, 20 * 1024**3)
    check_file(OLD_ROOT, 20 * 1024**3)
    check_file(OLD_GZIP, 1 * 1024**3)
    check_file(OLD_GZIP.with_name(OLD_GZIP.name + ".manifest.json"))
    if ARCHIVE.exists() or ARCHIVE.is_symlink() or MANIFEST.exists() or MANIFEST.is_symlink():
        raise RuntimeError("RECOVERY_ALREADY_PUBLISHED")
    for tmp in (ARCHIVE.with_name("." + ARCHIVE.name + ".incomplete"),
                BACKUPS / ".christiania_v34_restore_probe.tmp.db"):
        if tmp.exists() or tmp.is_symlink():
            raise RuntimeError("LEFTOVER_TRIAL_REQUIRES_INSPECTION:" + tmp.name)
    free = shutil.disk_usage(BACKUPS).free
    if free < PARTIAL.stat().st_size + RESERVE_BYTES + 4 * 1024**3:
        raise RuntimeError("INSUFFICIENT_RECOVERY_HEADROOM:" + str(free))
    before = PARTIAL.stat()
    time.sleep(2)
    after = PARTIAL.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
        raise RuntimeError("INCOMPLETE_COPY_STILL_CHANGING")
    details = structural_check(PARTIAL)
    if structural_check(LIVE)["schema_version"] != details["schema_version"]:
        raise RuntimeError("LIVE_SCHEMA_CHANGED")
    return after, details


def finalize(*, release_source: bool) -> None:
    with LOCK.open("a+b") as fd:
        fcntl.flock(fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        stat, metadata = preflight()
        report("PREFLIGHT_PASSED", source_bytes=stat.st_size, **metadata)
        gz_temp = ARCHIVE.with_name("." + ARCHIVE.name + ".incomplete")
        restore_temp = BACKUPS / ".christiania_v34_restore_probe.tmp.db"
        digest = hashlib.sha256()
        plain_bytes = 0
        completed = False
        try:
            with gz_temp.open("xb") as target:
                os.chmod(gz_temp, 0o640)
                with gzip.GzipFile(filename="", mode="wb", fileobj=target, compresslevel=1, mtime=0) as zipped:
                    with PARTIAL.open("rb") as source:
                        while data := source.read(CHUNK):
                            digest.update(data)
                            zipped.write(data)
                            plain_bytes += len(data)
                            tick("COMPRESSING", plain_bytes)
                target.flush()
                os.fsync(target.fileno())
            if plain_bytes != stat.st_size:
                raise RuntimeError("COMPRESSED_BYTE_COUNT_MISMATCH")
            if shutil.disk_usage(BACKUPS).free < stat.st_size + RESERVE_BYTES:
                raise RuntimeError("RESTORE_PROBE_HEADROOM_TOO_LOW")
            compressed_digest = hashlib.sha256()
            with gz_temp.open("rb") as source:
                while data := source.read(CHUNK):
                    compressed_digest.update(data)
                    tick("HASHING_COMPRESSED", source.tell())
            report("RESTORE_TRIAL_START", compressed_bytes=gz_temp.stat().st_size)
            test_sha = hashlib.sha256()
            test_bytes = 0
            with gzip.open(gz_temp, "rb") as source, restore_temp.open("xb") as target:
                os.chmod(restore_temp, 0o640)
                while data := source.read(CHUNK):
                    target.write(data)
                    test_sha.update(data)
                    test_bytes += len(data)
                    tick("RESTORING", test_bytes)
                target.flush()
                os.fsync(target.fileno())
            if test_bytes != plain_bytes or test_sha.digest() != digest.digest():
                raise RuntimeError("RESTORE_SHA256_OR_SIZE_MISMATCH")
            restored = structural_check(restore_temp)
            if restored != metadata:
                raise RuntimeError("RESTORED_SQLITE_METADATA_MISMATCH")
            if (PARTIAL.stat().st_size, PARTIAL.stat().st_mtime_ns, PARTIAL.stat().st_ino) != (
                stat.st_size, stat.st_mtime_ns, stat.st_ino
            ):
                raise RuntimeError("SNAPSHOT_CHANGED_DURING_ARCHIVE")
            report("RESTORE_TRIAL_PASSED", restored_bytes=test_bytes, **restored)
            manifest = {
                "format_version": 2,
                "schema_version": 34,
                "source_filename": "christiania_backup_20261017T203934Z.db",
                "backup_filename": ARCHIVE.name,
                "source_size_bytes": plain_bytes,
                "source_sha256": digest.hexdigest(),
                "compressed_size_bytes": gz_temp.stat().st_size,
                "compressed_sha256": compressed_digest.hexdigest(),
                "compression": "gzip",
                "compression_level": 1,
                "snapshot_method": "VACUUM_INTO",
                "snapshot_copy_done_in_journal_utc": "2026-10-17T20:47:11.996813+00:00",
                "verification_level": "archive_roundtrip_and_sqlite_structural",
                "restore_trial_completed": True,
                "restore_payload_sha256_equal_to_source": True,
                "full_integrity_check": None,
                "quick_check": None,
                "foreign_key_check": "NOT_RUN",
                "verified_at_utc": datetime.now(UTC).isoformat(),
            }
            man_temp = MANIFEST.with_name("." + MANIFEST.name + ".incomplete")
            with man_temp.open("x", encoding="utf8") as f:
                os.chmod(man_temp, 0o640)
                json.dump(manifest, f, sort_keys=True, indent=2)
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(gz_temp, ARCHIVE)
            os.replace(man_temp, MANIFEST)
            fsync_parent(ARCHIVE)
            completed = True
            if release_source:
                # This is the original *incomplete-named* snapshot only. Old root
                # backups, previous gzip archive, and live DB are NEVER deleted.
                PARTIAL.unlink()
                fsync_parent(PARTIAL)
            report("COMPLETE", archive=str(ARCHIVE), bytes=ARCHIVE.stat().st_size,
                   source_released=release_source, verification_level=manifest["verification_level"],
                   old_independent_deep_backup_preserved=OLD_GZIP.exists())
        finally:
            if restore_temp.exists():
                restore_temp.unlink()
            if not completed and gz_temp.exists():
                gz_temp.unlink()


if __name__ == "__main__":
    try:
        finalize(release_source="--release-source-after-restore" in sys.argv[1:])
    except BaseException as error:
        try:
            report("FAILED", error=f"{type(error).__name__}:{error}")
        finally:
            raise
