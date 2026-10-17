#!/usr/bin/env python3
"""Bounded, standalone gzip promotion of the newly routine-verified v34 copy.

The old October recovery points are mandatory and never modified. Operates
only on a separately mounted recovery volume; no live DB or schema changes.
Full SQLite integrity_check is deliberately NOT asserted here. A future deep
restore audit remains required to upgrade the verification level.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import time
from datetime import UTC, datetime

ROOT = Path("/mnt/HC_Volume_107172834")
BACKUPS = ROOT / "backups"
PLAIN = BACKUPS / "christiania_backup_20261017T203934Z.db"
STATUS = BACKUPS / "volume_v34_compression_status.json"
OLD_ARCHIVE = BACKUPS / "christiania_backup_20261008T233215Z.db.gz"
ROOT_PROTECTION = (
    Path("/var/lib/christiania/backups/christiania_backup_20261001T233013Z.db"),
    Path("/var/lib/christiania/backups/christiania_backup_20261008T233215Z.db"),
)
RESERVE = 15 * 1024**3
CHUNK = 8 * 1024**2
COMPRESS_LIMIT_SECONDS = 1800
VERIFY_LIMIT_SECONDS = 900


def report(phase: str, **fields: object) -> None:
    payload = {"phase": phase, "at_utc": datetime.now(UTC).isoformat(), **fields}
    print(json.dumps(payload, sort_keys=True), flush=True)
    temp = STATUS.with_name("." + STATUS.name + ".tmp")
    with temp.open("w", encoding="utf-8") as fd:
        json.dump(payload, fd, indent=2, sort_keys=True)
        fd.flush()
        os.fsync(fd.fileno())
    os.replace(temp, STATUS)


def hash_stream(stream, *, deadline: float) -> str:
    digest = hashlib.sha256()
    while True:
        if time.monotonic() > deadline:
            raise TimeoutError("ARCHIVE_VERIFICATION_DEADLINE_EXCEEDED")
        block = stream.read(CHUNK)
        if not block:
            break
        digest.update(block)
    return digest.hexdigest()


def hash_file(path: Path, *, limit: int) -> str:
    with path.open("rb") as fd:
        return hash_stream(fd, deadline=time.monotonic() + limit)


def preflight(*, root: Path, backups: Path, plain: Path, production: bool = True) -> dict:
    if production:
        if not root.is_mount() or root.is_symlink() or (
            os.stat(root).st_dev == os.stat("/")
        ):
            raise RuntimeError("RECOVERY_VOLUME_NOT_INDEPENDENT_MOUNT")
        if not backups.resolve(strict=True).is_relative_to(root.resolve(strict=True)):
            raise RuntimeError("BACKUPS_ESCAPE_RECOVERY_VOLUME")
        if not OLD_ARCHIVE.is_file() or not (backups / (OLD_ARCHIVE.name + ".manifest.json")).is_file():
            raise RuntimeError("PREVIOUS_COMPRESSED_RECOVERY_MISSING")
        for p in ROOT_PROTECTION:
            if not p.is_file() or p.is_symlink():
                raise RuntimeError(f"PREVIOUS_ROOT_RECOVERY_MISSING:{p.name}")
    if not plain.is_file() or plain.is_symlink() or plain.stat().st_size < 1:
        raise RuntimeError("PROMOTED_PLAINTEXT_SNAPSHOT_MISSING")
    proof_path = plain.with_name(plain.name + ".manifest.json")
    if not proof_path.is_file() or proof_path.is_symlink():
        raise RuntimeError("PLAINTEXT_VERIFICATION_EVIDENCE_MISSING")
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    required = {
        "schema_version": 34,
        "verification_level": "routine",
        "quick_check": "ok",
        "integrity_check": None,
        "foreign_key_violation_count": 0,
        "snapshot_method": "VACUUM_INTO",
        "snapshot_path": str(plain),
        "snapshot_bytes": plain.stat().st_size,
    }
    for key, value in required.items():
        if proof.get(key) != value:
            raise RuntimeError(f"PLAINTEXT_EVIDENCE_DISAGREES:{key}")
    sha = proof.get("snapshot_sha256")
    if not isinstance(sha, str) or len(sha) != 64 or any(
        c not in "0123456789abcdef" for c in sha
    ):
        raise RuntimeError("INVALID_PLAINTEXT_SHA256_EVIDENCE")
    final = plain.with_name(plain.name + ".gz")
    if any(p.exists() or p.is_symlink() for p in (
        final, final.with_name(final.name + ".manifest.json")
    )):
        raise FileExistsError("COMPRESSED_RECOVERY_ALREADY_EXISTS")
    disk = shutil.disk_usage(backups)
    required_free = plain.stat().st_size + max(RESERVE, int(disk.total * .15))
    if disk.free <= required_free:
        raise RuntimeError(
            f"INSUFFICIENT_COMPRESSION_HEADROOM:{disk.free}:{required_free}"
        )
    return proof


def compress_routine(*, root: Path = ROOT, backups: Path = BACKUPS,
                     plain: Path = PLAIN, production: bool = True) -> Path:
    import fcntl
    # Verify the genuine mount BEFORE creating even the tiny lock file.
    preflight(root=root, backups=backups, plain=plain, production=production)
    lock = backups / ".christiania_volume_v34_compress.lock"
    with lock.open("a+b") as lock_fd:
        fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        proof = preflight(root=root, backups=backups, plain=plain, production=production)
        compressed = plain.with_name(plain.name + ".gz")
        manifest = compressed.with_name(compressed.name + ".manifest.json")
        temporary = compressed.with_name("." + compressed.name + ".incomplete")
        if temporary.exists() or temporary.is_symlink():
            raise FileExistsError("TEMPORARY_ARCHIVE_ALREADY_EXISTS")
        os.umask(0o077)
        digest = hashlib.sha256()
        started = time.monotonic()
        final_created = False
        report("COMPRESSING", source=str(plain), verification_level="routine")
        try:
            fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, "wb") as output:
                with gzip.GzipFile(filename="", mode="wb", fileobj=output,
                                   compresslevel=1, mtime=0) as archive:
                    with plain.open("rb") as source:
                        processed = 0
                        latest = started
                        while True:
                            if time.monotonic() - started > COMPRESS_LIMIT_SECONDS:
                                raise TimeoutError("COMPRESSION_DEADLINE_EXCEEDED")
                            chunk = source.read(CHUNK)
                            if not chunk:
                                break
                            digest.update(chunk)
                            archive.write(chunk)
                            processed += len(chunk)
                            now = time.monotonic()
                            if now - latest > 30:
                                report("COMPRESSING", processed_bytes=processed,
                                       elapsed_seconds=int(now - started))
                                latest = now
                output.flush()
                os.fsync(output.fileno())
            if digest.hexdigest() != proof["snapshot_sha256"]:
                raise RuntimeError("PLAIN_SNAPSHOT_HASH_CHANGED_DURING_COMPRESSION")
            with gzip.open(temporary, "rb") as reopened:
                expanded_sha = hash_stream(
                    reopened, deadline=time.monotonic() + VERIFY_LIMIT_SECONDS,
                )
            if expanded_sha != proof["snapshot_sha256"]:
                raise RuntimeError("COMPRESSED_PAYLOAD_HASH_MISMATCH")
            compressed_sha = hash_file(temporary, limit=VERIFY_LIMIT_SECONDS)
            payload = {
                "format_version": 2,
                "created_at": datetime.now(UTC).isoformat(),
                "backup_filename": compressed.name,
                "source_filename": plain.name,
                "schema_version": 34,
                "verification_level": "routine",
                "quick_check": "ok",
                "integrity_check": None,
                "foreign_key_violation_count": 0,
                "source_size_bytes": plain.stat().st_size,
                "compressed_size_bytes": temporary.stat().st_size,
                "source_sha256": proof["snapshot_sha256"],
                "compressed_sha256": compressed_sha,
                "compression": "gzip",
                "compression_level": 1,
            }
            staged = manifest.with_name("." + manifest.name + ".tmp")
            with staged.open("x", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, compressed)
            final_created = True
            os.replace(staged, manifest)
            if hash_file(compressed, limit=VERIFY_LIMIT_SECONDS) != compressed_sha:
                raise RuntimeError("COMPRESSED_BYTES_CHANGED_AFTER_PROMOTION")
            # Every previous recovery point remains available throughout.
            if production:
                preflight_old_points()
            plain.unlink()
            report("COMPLETE", compressed=str(compressed),
                   compressed_bytes=compressed.stat().st_size,
                   verification_level="routine",
                   independent_deep_restore_still_required=True)
            return compressed
        except BaseException as exc:
            report("FAILED", error=f"{type(exc).__name__}:{str(exc)[:160]}")
            if temporary.exists() and not temporary.is_symlink():
                temporary.unlink()
            if plain.exists() and final_created:
                compressed.unlink(missing_ok=True)
                manifest.unlink(missing_ok=True)
            raise


def preflight_old_points() -> None:
    if not OLD_ARCHIVE.is_file() or not (
        BACKUPS / (OLD_ARCHIVE.name + ".manifest.json")
    ).is_file():
        raise RuntimeError("PREVIOUS_VOLUME_RECOVERY_LOST")
    if any(not p.is_file() for p in ROOT_PROTECTION):
        raise RuntimeError("PREVIOUS_ROOT_RECOVERY_LOST")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--check-only", action="store_true")
    ap.add_argument("--compress", action="store_true")
    opts = ap.parse_args()
    if opts.check_only == opts.compress:
        ap.error("Specify exactly one mode.")
    if opts.check_only:
        print(json.dumps({"ready": True, "source": str(PLAIN),
                          "verification_level": preflight(
                              root=ROOT, backups=BACKUPS, plain=PLAIN
                          )["verification_level"]}), flush=True)
    else:
        compress_routine()
