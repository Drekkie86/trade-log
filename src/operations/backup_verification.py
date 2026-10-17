"""Explicit routine/deep SQLite recovery evidence.

Routine verification is NOT a substitute for a deep integrity audit. Both
levels include exact schema and complete referential-integrity validation.
Every scan and hash has a bounded cooperative deadline; outer systemd units
must also enforce a hard wall-clock timeout against blocked filesystem I/O.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, Literal

VerificationLevel = Literal["routine", "deep"]
VERIFY_LIMIT_SECONDS = 900
HASH_LIMIT_SECONDS = 900
CHUNK_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True)
class SqliteVerification:
    level: VerificationLevel
    schema_version: int
    quick_check: str | None
    integrity_check: str | None
    foreign_key_violation_count: int

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class PlainBackupEvidence:
    format_version: int
    backup_filename: str
    schema_version: int
    verification_level: str
    quick_check: str | None
    integrity_check: str | None
    foreign_key_violation_count: int
    source_size_bytes: int
    source_sha256: str
    verified_at_utc: str
    snapshot_method: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def verify_sqlite_snapshot(
    path: Path,
    *,
    expected_schema: int,
    level: VerificationLevel = "routine",
    max_seconds: int = VERIFY_LIMIT_SECONDS,
    progress: Callable[[str], None] | None = None,
) -> SqliteVerification:
    if level not in ("routine", "deep"):
        raise ValueError("Unknown backup verification level.")
    if max_seconds < 1:
        raise ValueError("SQLite verification timeout must be positive.")
    if not path.is_file() or path.is_symlink():
        raise RuntimeError("Snapshot is missing or a symlink.")
    started = time.monotonic()
    last_heartbeat = started
    timed_out = False

    def on_progress() -> int:
        nonlocal timed_out, last_heartbeat
        now = time.monotonic()
        if now - started >= max_seconds:
            timed_out = True
            return 1
        if progress is not None and now - last_heartbeat >= 30:
            progress(f"verification: working level={level} elapsed_seconds={int(now-started)}")
            last_heartbeat = now
        return 0

    uri = path.resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=30.0)
    try:
        conn.execute("PRAGMA query_only=ON")
        conn.set_progress_handler(on_progress, 10_000)
        row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
        if not row or row[0] is None:
            raise RuntimeError("Backup has no schema version.")
        schema = int(row[0])
        if schema != expected_schema:
            raise RuntimeError(
                f"Backup schema v{schema} does not match expected v{expected_schema}."
            )
        pragma = "quick_check(1)" if level == "routine" else "integrity_check"
        if progress is not None:
            progress(f"verification: {pragma} started level={level}")
        check = str(conn.execute(f"PRAGMA {pragma}").fetchone()[0])
        if check != "ok":
            raise RuntimeError(f"Backup {pragma} failed: {check}")
        if progress is not None:
            progress(f"verification: {pragma} completed result=ok")
            progress("verification: foreign_key_check started")
        # Fail on first violation without allocating an unbounded result list.
        fk_first = conn.execute("PRAGMA foreign_key_check").fetchone()
        fk_count = 1 if fk_first is not None else 0
        if progress is not None:
            progress(f"verification: foreign_key_check completed violations={fk_count}")
        if fk_count:
            raise RuntimeError("Backup foreign_key_check returned violations.")
        return SqliteVerification(
            level=level, schema_version=schema,
            quick_check=check if level == "routine" else None,
            integrity_check=check if level == "deep" else None,
            foreign_key_violation_count=0,
        )
    except sqlite3.OperationalError as exc:
        if timed_out:
            raise TimeoutError(
                f"SQLite {level} verification exceeded {max_seconds} seconds"
            ) from exc
        raise
    finally:
        conn.set_progress_handler(None, 0)
        conn.close()


def hash_snapshot(
    path: Path,
    *,
    max_seconds: int = HASH_LIMIT_SECONDS,
    progress: Callable[[str], None] | None = None,
) -> str:
    if max_seconds < 1:
        raise ValueError("Snapshot hash timeout must be positive.")
    started = time.monotonic()
    latest = started
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            if time.monotonic() - started >= max_seconds:
                raise TimeoutError(f"Snapshot SHA-256 exceeded {max_seconds} seconds")
            block = handle.read(CHUNK_BYTES)
            if not block:
                break
            digest.update(block)
            if progress is not None and time.monotonic() - latest >= 30:
                progress(f"hash: working elapsed_seconds={int(time.monotonic()-started)}")
                latest = time.monotonic()
    return digest.hexdigest()


def evidence_path_for(path: Path) -> Path:
    return path.with_name(path.name + ".manifest.json")


def _fsync_dir(path: Path) -> None:
    if os.name == "nt":
        return
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def publish_plain_evidence(
    backup: Path,
    verification: SqliteVerification,
    *,
    sha256: str,
    snapshot_method: str = "VACUUM_INTO",
) -> PlainBackupEvidence:
    if not backup.is_file() or backup.is_symlink() or backup.stat().st_size <= 0:
        raise RuntimeError("Cannot certify missing or empty backup.")
    if len(sha256) != 64 or any(c not in "0123456789abcdef" for c in sha256):
        raise ValueError("Source SHA-256 must be a 64-digit lowercase hex digest.")
    evidence = PlainBackupEvidence(
        format_version=1, backup_filename=backup.name,
        schema_version=verification.schema_version,
        verification_level=verification.level,
        quick_check=verification.quick_check,
        integrity_check=verification.integrity_check,
        foreign_key_violation_count=verification.foreign_key_violation_count,
        source_size_bytes=backup.stat().st_size, source_sha256=sha256,
        verified_at_utc=datetime.now(UTC).isoformat(),
        snapshot_method=snapshot_method,
    )
    final = evidence_path_for(backup)
    if final.exists() or final.is_symlink():
        raise FileExistsError(f"Recovery evidence already exists: {final}")
    temp = final.with_name(f".{final.name}.{os.getpid()}.tmp")
    try:
        with temp.open("x", encoding="utf-8") as handle:
            json.dump(evidence.as_dict(), handle, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, final)
        _fsync_dir(final.parent)
    finally:
        if temp.exists():
            temp.unlink()
    return evidence


def read_plain_evidence(
    backup: Path,
    *,
    source_sha256: str,
) -> PlainBackupEvidence:
    path = evidence_path_for(backup)
    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError(f"Backup evidence missing: {path}")
    evidence = PlainBackupEvidence(**json.loads(path.read_text(encoding="utf-8")))
    if (evidence.format_version != 1 or evidence.backup_filename != backup.name
            or evidence.source_size_bytes != backup.stat().st_size
            or evidence.source_sha256 != source_sha256
            or evidence.foreign_key_violation_count != 0):
        raise RuntimeError("Plain backup evidence does not match source bytes.")
    if evidence.verification_level == "routine":
        valid = evidence.quick_check == "ok" and evidence.integrity_check is None
    elif evidence.verification_level == "deep":
        valid = evidence.integrity_check == "ok"
    else:
        valid = False
    if not valid:
        raise RuntimeError("Plain backup evidence has no valid verification result.")
    return evidence
