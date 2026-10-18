#!/usr/bin/env python3
"""Christiania standalone independent-volume nightly SQLite recovery.

Never writes to the live database. VACUUM INTO commits a transactionally
consistent copy; compressed SHA/CRC and an actual independent restored SQLite
file are verified before publication. Does NOT pretend PRAGMA integrity_check
or foreign_key_check was performed. Deep validation remains a separate job.
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
HISTORIC = BACKUPS / "christiania_backup_20261008T233215Z.db.gz"
HISTORIC_MANIFEST = BACKUPS / (HISTORIC.name + ".manifest.json")
ROOT_HISTORIC = Path("/var/lib/christiania/backups/christiania_backup_20261008T233215Z.db")
STATUS = BACKUPS / "volume_backup_scheduler_status.json"
AUDIT_STATUS = BACKUPS / "volume_backup_restore_audit_status.json"
LOCK = BACKUPS / ".christiania_backup.lock"
CHUNK = 8 * 1024 * 1024
RESERVE = 15 * 1024**3
MAX_RUNTIME = 5400
KEEP_NEW_ARCHIVES = 3
_start = time.monotonic()
_last = _start


def report(phase: str, **details: object) -> None:
    payload = {"phase": phase, "at_utc": datetime.now(UTC).isoformat(), **details}
    print(json.dumps(payload, sort_keys=True), flush=True)
    temp = STATUS.with_name("." + STATUS.name + ".new")
    with temp.open("w", encoding="utf8") as f:
        os.chmod(temp, 0o640)
        json.dump(payload, f, sort_keys=True, indent=2)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp, STATUS)


def checkpoint(stage: str, count: int = 0) -> int:
    global _last
    now = time.monotonic()
    if now - _start >= MAX_RUNTIME:
        raise TimeoutError("NIGHTLY_BACKUP_EXCEEDED_HARD_DEADLINE")
    if now - _last >= 30:
        report(stage, processed_bytes=count, elapsed_seconds=int(now-_start))
        _last = now
    return 0


def fsync_dir() -> None:
    fd = os.open(BACKUPS, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def safe_file(path: Path, min_size: int = 1) -> None:
    if not path.is_file() or path.is_symlink() or path.stat().st_size < min_size:
        raise RuntimeError("MISSING_OR_UNSAFE_FILE:" + path.name)


def metadata(path: Path, *, immutable: bool = True) -> dict[str, int]:
    safe_file(path)
    uri = path.resolve().as_uri() + ("?mode=ro&immutable=1" if immutable else "?mode=ro")
    db = sqlite3.connect(uri, uri=True, timeout=10)
    try:
        db.execute("PRAGMA query_only=ON")
        version = db.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
        page_count = db.execute("PRAGMA page_count").fetchone()[0]
        page_size = db.execute("PRAGMA page_size").fetchone()[0]
        table_count = db.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
        if version is None or page_count < 100 or table_count < 5:
            raise RuntimeError("BAD_SQLITE_METADATA")
        if immutable and page_count * page_size != path.stat().st_size:
            raise RuntimeError("SQLITE_FILE_PAGE_LENGTH_MISMATCH")
        return {"schema_version": int(version), "page_count": int(page_count),
                "page_size": int(page_size), "table_count": int(table_count)}
    finally:
        db.close()


def preflight() -> dict[str, int]:
    if not VOLUME.is_mount() or VOLUME.is_symlink() or BACKUPS.is_symlink():
        raise RuntimeError("RECOVERY_VOLUME_NOT_INDEPENDENT_MOUNT")
    if os.stat(LIVE).st_dev == os.stat(VOLUME).st_dev:
        raise RuntimeError("RECOVERY_VOLUME_SAME_DEVICE_AS_LIVE")
    safe_file(LIVE, 20 * 1024**3)
    safe_file(HISTORIC, 1024**3)
    safe_file(HISTORIC_MANIFEST)
    safe_file(ROOT_HISTORIC, 20 * 1024**3)
    # A killed/failed backup is not silently repeated with another 30 GiB
    # temporary file. An operator must first resolve the orphaned evidence.
    for pattern in (".christiania_backup_*.incomplete.db",
                    ".christiania_backup_*.db.gz.incomplete"):
        if next(BACKUPS.glob(pattern), None) is not None:
            raise RuntimeError("UNRESOLVED_INCOMPLETE_RECOVERY_FILE")
    baseline = json.loads(HISTORIC_MANIFEST.read_text(encoding="utf8"))
    if baseline.get("integrity_check") != "ok" or baseline.get("foreign_key_violation_count") != 0:
        raise RuntimeError("INDEPENDENT_PRIOR_FULL_CHECK_NOT_PROVEN")
    if baseline.get("schema_version") != 34:
        raise RuntimeError("INDEPENDENT_PRIOR_BACKUP_WRONG_VERSION")
    current = metadata(LIVE, immutable=False)
    if current["schema_version"] < 34:
        raise RuntimeError("LIVE_SCHEMA_UNEXPECTED")
    disk = shutil.disk_usage(BACKUPS)
    logical_size = current["page_count"] * current["page_size"]
    if disk.free < logical_size + max(8 * 1024**3, logical_size // 5) + RESERVE:
        raise RuntimeError(f"INSUFFICIENT_VOLUME_HEADROOM:{disk.free}:{logical_size}")
    return current


def run(*, fixture: bool = False) -> None:
    BACKUPS.mkdir(parents=True, exist_ok=True) if fixture else None
    with LOCK.open("a+b") as lock_fd:
        fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        before = preflight() if not fixture else metadata(LIVE, immutable=False)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        partial = BACKUPS / f".christiania_backup_{stamp}.incomplete.db"
        gz = BACKUPS / f"christiania_backup_{stamp}.db.gz"
        zipped = BACKUPS / f".{gz.name}.incomplete"
        restored = BACKUPS / f".christiania_trial_{stamp}.tmp.db"
        manifest = BACKUPS / (gz.name + ".manifest.json")
        if any(p.exists() or p.is_symlink() for p in (partial, gz, zipped, restored, manifest)):
            raise RuntimeError("DESTINATION_EXISTS")
        report("START", expected_schema=before["schema_version"], live_bytes=LIVE.stat().st_size)
        source_created = False
        archive_published = False
        try:
            uri = LIVE.resolve().as_uri() + "?mode=ro"
            source_created = True  # retain interrupted copy for inspection; never silently discard
            with sqlite3.connect(uri, uri=True, timeout=30) as conn:
                conn.set_progress_handler(lambda: checkpoint("SNAPSHOTTING"), 20000)
                try:
                    conn.execute("VACUUM INTO ?", (str(partial),))
                finally:
                    conn.set_progress_handler(None, 0)
            source_created = True
            source_stat = partial.stat()
            if source_stat.st_size < LIVE.stat().st_size // 2:
                raise RuntimeError("VACUUM_OUTPUT_SUSPICIOUSLY_SMALL")
            after = metadata(partial)
            if after["schema_version"] != before["schema_version"]:
                raise RuntimeError("SCHEMA_CHANGED_DURING_COPY")
            report("SNAPSHOT_COMPLETE", size_bytes=source_stat.st_size, schema=after["schema_version"])
            digest = hashlib.sha256()
            uncompressed_bytes = 0
            with zipped.open("xb") as target:
                os.chmod(zipped, 0o640)
                with gzip.GzipFile(filename="", fileobj=target, mode="wb", compresslevel=1, mtime=0) as stream:
                    with partial.open("rb") as original:
                        while data := original.read(CHUNK):
                            stream.write(data)
                            digest.update(data)
                            uncompressed_bytes += len(data)
                            checkpoint("COMPRESSING", uncompressed_bytes)
                target.flush()
                os.fsync(target.fileno())
            if uncompressed_bytes != source_stat.st_size:
                raise RuntimeError("SNAPSHOT_SIZE_CHANGED")
            test_digest = hashlib.sha256()
            test_count = 0
            with gzip.open(zipped, "rb") as stream:
                while data := stream.read(CHUNK):
                    test_digest.update(data)
                    test_count += len(data)
                    checkpoint("VALIDATING_GZIP_CRC_SHA", test_count)
            if test_count != uncompressed_bytes or test_digest.digest() != digest.digest():
                raise RuntimeError("GZIP_CRC_OR_SHA256_MISMATCH")
            # Now the compressed stream exactly reproduces the immutable copy.
            # The live DB and all earlier backup points remain untouched.
            if source_stat.st_ino != partial.stat().st_ino or source_stat.st_mtime_ns != partial.stat().st_mtime_ns:
                raise RuntimeError("SOURCE_CHANGED_DURING_COMPRESSION")
            partial.unlink()
            fsync_dir()
            source_created = False
            if shutil.disk_usage(BACKUPS).free < uncompressed_bytes + RESERVE:
                raise RuntimeError("INSUFFICIENT_RESTORE_REHEARSAL_HEADROOM")
            report("RESTORING_SEPARATE_SQLITE_FILE", bytes=uncompressed_bytes)
            restore_hash = hashlib.sha256()
            restored_bytes = 0
            with gzip.open(zipped, "rb") as compressed, restored.open("xb") as target:
                os.chmod(restored, 0o640)
                while data := compressed.read(CHUNK):
                    target.write(data)
                    restore_hash.update(data)
                    restored_bytes += len(data)
                    checkpoint("RESTORING", restored_bytes)
                target.flush()
                os.fsync(target.fileno())
            if restored_bytes != uncompressed_bytes or restore_hash.digest() != digest.digest():
                raise RuntimeError("ACTUAL_RESTORE_BYTE_SHA_MISMATCH")
            check = metadata(restored)
            if check != after:
                raise RuntimeError("RESTORED_SCHEMA_OR_PAGE_METADATA_MISMATCH")
            sha_gz = hashlib.sha256()
            with zipped.open("rb") as f:
                while data := f.read(CHUNK):
                    sha_gz.update(data)
                    checkpoint("FINAL_ARCHIVE_HASH", f.tell())
            data = {
                "format_version": 3,
                "backup_filename": gz.name,
                "source_filename": partial.name,
                "schema_version": check["schema_version"],
                "source_size_bytes": uncompressed_bytes,
                "source_sha256": digest.hexdigest(),
                "compressed_size_bytes": zipped.stat().st_size,
                "compressed_sha256": sha_gz.hexdigest(),
                "compression": "gzip",
                "snapshot_method": "VACUUM_INTO",
                "verification_level": "archive_stream_sha256_crc_plus_real_restore_structural",
                "restore_trial_completed": True,
                "full_sqlite_integrity_check": None,
                "quick_check": None,
                "foreign_key_check": "NOT_RUN",
                "created_at": datetime.now(UTC).isoformat(),
            }
            staged = BACKUPS / ("." + manifest.name + ".tmp")
            with staged.open("x", encoding="utf8") as file:
                os.chmod(staged, 0o640)
                json.dump(data, file, sort_keys=True, indent=2)
                file.write("\n")
                file.flush()
                os.fsync(file.fileno())
            os.replace(zipped, gz)
            os.replace(staged, manifest)
            fsync_dir()
            archive_published = True
            report("COMPLETE", archive=str(gz), schema_version=check["schema_version"],
                   source_sha256=digest.hexdigest(), verified_restore_bytes=restored_bytes)
            # Keep oldest fully checked anchor. Rotate *only* new format-3 archives
            # after successful publication and with >= 2 current points retained.
            candidates = []
            for p in sorted(BACKUPS.glob("christiania_backup_*.db.gz")):
                if p == HISTORIC:
                    continue
                proof = p.with_name(p.name + ".manifest.json")
                if proof.is_file():
                    try:
                        if json.loads(proof.read_text(encoding="utf8")).get("format_version") == 3:
                            candidates.append((p, proof))
                    except (OSError, ValueError):
                        pass
            for old_archive, old_manifest in candidates[:-KEEP_NEW_ARCHIVES]:
                old_archive.unlink()
                old_manifest.unlink()
            if len(candidates) > KEEP_NEW_ARCHIVES:
                fsync_dir()
        finally:
            if restored.exists():
                restored.unlink()
            if source_created and partial.exists():
                # Never delete an unfinished snapshot if verification failed:
                # it may be salvageable; the next backup fails closed on disk.
                report("INCOMPLETE_COPY_PRESERVED", filename=partial.name)
            if not archive_published and zipped.exists():
                report("UNPUBLISHED_GZIP_PRESERVED", filename=zipped.name)



def audit_report(phase: str, **details: object) -> None:
    payload = {"phase": phase, "at_utc": datetime.now(UTC).isoformat(), **details}
    print(json.dumps(payload, sort_keys=True), flush=True)
    temporary = AUDIT_STATUS.with_name("." + AUDIT_STATUS.name + ".new")
    with temporary.open("w", encoding="utf8") as f:
        os.chmod(temporary, 0o640)
        json.dump(payload, f, sort_keys=True, indent=2)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(temporary, AUDIT_STATUS)


def audit_restore(*, fixture: bool = False) -> None:
    """Reopen most recent archived recovery as a *separate* SQLite file.

    Verifies stored archive SHA, gzip CRC, restored plaintext SHA, size and
    SQLite schema/metadata. Deliberately omits slow whole-DB integrity checks.
    """
    with LOCK.open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        if not fixture:
            if not VOLUME.is_mount() or VOLUME.is_symlink():
                raise RuntimeError("RESTORE_VOLUME_NOT_MOUNTED")
            safe_file(HISTORIC, 1024**3)
            safe_file(HISTORIC_MANIFEST)
        options = []
        for p in BACKUPS.glob("christiania_backup_*.db.gz"):
            if p.is_symlink() or not p.is_file():
                continue
            proof = p.with_name(p.name + ".manifest.json")
            if proof.is_file() and not proof.is_symlink():
                options.append(p)
        if not options:
            raise RuntimeError("NO_ARCHIVE_WITH_MANIFEST_TO_RESTORE")
        latest = max(options, key=lambda p: p.name)
        proof = json.loads((BACKUPS / (latest.name + ".manifest.json")).read_text(encoding="utf8"))
        if proof.get("backup_filename") != latest.name:
            raise RuntimeError("RESTORE_MANIFEST_FILENAME_MISMATCH")
        source_hash = proof.get("source_sha256")
        archive_hash = proof.get("compressed_sha256")
        expected_size = proof.get("source_size_bytes")
        if not isinstance(expected_size, int) or expected_size < 1:
            raise RuntimeError("INVALID_RESTORE_SOURCE_SIZE")
        if (not isinstance(source_hash, str) or len(source_hash) != 64 or
                not isinstance(archive_hash, str) or len(archive_hash) != 64):
            raise RuntimeError("INVALID_RESTORE_DIGESTS")
        if latest.stat().st_size != proof.get("compressed_size_bytes"):
            raise RuntimeError("COMPRESSED_SIZE_MISMATCH")
        if not fixture and shutil.disk_usage(BACKUPS).free < expected_size + RESERVE:
            raise RuntimeError("INSUFFICIENT_WEEKLY_RESTORE_HEADROOM")
        restored = BACKUPS / ".christiania_weekly_restore_trial.tmp.db"
        if restored.exists() or restored.is_symlink():
            raise RuntimeError("PRIOR_WEEKLY_RESTORE_SCRATCH_PRESENT")
        audit_report("AUDITING", archive=latest.name, expected_size_bytes=expected_size)
        try:
            h = hashlib.sha256()
            with latest.open("rb") as archive_stream:
                while data := archive_stream.read(CHUNK):
                    h.update(data)
                    checkpoint("AUDIT_ARCHIVE_HASH", archive_stream.tell())
            if h.hexdigest() != archive_hash:
                raise RuntimeError("ARCHIVE_SHA256_MISMATCH")
            plain_hash = hashlib.sha256()
            total = 0
            with gzip.open(latest, "rb") as unzipped, restored.open("xb") as dest:
                os.chmod(restored, 0o640)
                while data := unzipped.read(CHUNK):
                    dest.write(data)
                    total += len(data)
                    plain_hash.update(data)
                    checkpoint("AUDIT_RESTORE", total)
                dest.flush()
                os.fsync(dest.fileno())
            if total != expected_size or plain_hash.hexdigest() != source_hash:
                raise RuntimeError("RESTORED_SHA_OR_SIZE_MISMATCH")
            details = metadata(restored)
            if details["schema_version"] != proof["schema_version"]:
                raise RuntimeError("RESTORED_SCHEMA_MISMATCH")
            audit_report("PASSED", archive=latest.name, restored_size_bytes=total,
                         schema_version=details["schema_version"],
                         verification_level="full_byte_hash_gzip_crc_and_separate_sqlite_read")
        finally:
            if restored.exists():
                restored.unlink()


if __name__ == "__main__":
    try:
        if "--restore-audit" in sys.argv[1:]:
            audit_restore()
        else:
            run()
    except BaseException as exc:
        try:
            if "--restore-audit" in sys.argv[1:]:
                audit_report("FAILED", error=f"{type(exc).__name__}:{exc}")
            else:
                report("FAILED", error=f"{type(exc).__name__}:{exc}")
        finally:
            raise
