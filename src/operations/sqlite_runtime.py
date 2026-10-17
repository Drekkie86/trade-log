from __future__ import annotations

import os
import sqlite3
import shutil
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

from src.config import get_runtime_setting
from src.operations.recovery_volume_guard import require_recovery_volume_path
from src.database.repository import (
    EXPECTED_SCHEMA_VERSION,
    resolve_db_path,
)
from src.operations.backup_compression import (
    backup_data_files,
    manifest_path_for,
)
from src.operations.backup_verification import (
    SqliteVerification,
    evidence_path_for,
    hash_snapshot,
    publish_plain_evidence,
    verify_sqlite_snapshot,
)


DEFAULT_BACKUP_RETENTION = 14
DEFAULT_BACKUP_MIN_FREE_BYTES = 15 * 1024**3
DEFAULT_BACKUP_MIN_FREE_FRACTION = 0.15
BACKUP_SNAPSHOT_TIMEOUT_SECONDS = 1800
BACKUP_SNAPSHOT_PROGRESS_INTERVAL_SECONDS = 30


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
class BackupCapacityPlan:
    filesystem_total_bytes: int
    filesystem_free_bytes: int
    logical_source_bytes: int
    required_free_bytes: int
    retention: int
    preprune_keep: int
    current_backup_count: int
    reclaimable_bytes: int
    projected_free_bytes: int
    feasible_after_safe_prune: bool

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class BackupResult:
    source_path: str
    backup_path: str
    schema_version: int
    integrity_check: str | None
    foreign_key_violation_count: int
    pruned_count: int
    verification_level: str = "unknown"
    quick_check: str | None = None
    source_sha256: str | None = None

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def resolve_backup_dir(
    backup_dir: str | Path | None = None,
) -> Path:
    if backup_dir is not None:
        return require_recovery_volume_path(Path(backup_dir).expanduser())

    configured = get_runtime_setting(
        "CHRISTIANIA_BACKUP_DIR"
    )

    if configured:
        return require_recovery_volume_path(Path(configured).expanduser())

    return require_recovery_volume_path(
        Path(__file__).resolve().parents[2] / "backups"
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

    # Read-only means no schema mutation at all, including TEMP objects.
    # Read models must target persistent compatibility/normalized views
    # explicitly rather than relying on connection-local shims.
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
    *,
    deep_integrity: bool = True,
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

        quick_check = None
        fk_count = None

        if deep_integrity:
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


def _runtime_nonnegative_int(name: str, default: int) -> int:
    raw = get_runtime_setting(name)
    if raw in (None, ""):
        return default
    value = int(raw)
    if value < 0:
        raise ValueError(f"{name} cannot be negative.")
    return value


def _runtime_nonnegative_float(name: str, default: float) -> float:
    raw = get_runtime_setting(name)
    if raw in (None, ""):
        return default
    value = float(raw)
    if value < 0:
        raise ValueError(f"{name} cannot be negative.")
    return value


def backup_logical_source_bytes(
    source: Path,
) -> int:
    """Return the logical SQLite size that an online backup must materialize.

    In WAL mode the main `.db` file can lag committed growth held in the WAL.
    The backup API writes the logical page set, so capacity must use the larger
    of the main-file size and `page_count * page_size`.
    """
    uri = source.resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(
        uri,
        uri=True,
        timeout=30.0,
    )
    try:
        page_size = int(
            conn.execute(
                "PRAGMA page_size;"
            ).fetchone()[0]
        )
        page_count = int(
            conn.execute(
                "PRAGMA page_count;"
            ).fetchone()[0]
        )
    finally:
        conn.close()

    logical = page_size * page_count
    return max(
        int(source.stat().st_size),
        logical,
    )


def backup_required_free_bytes(
    *,
    source_size_bytes: int,
    filesystem_total_bytes: int,
) -> int:
    """Free bytes required before starting a full verified backup.

    The temporary full SQLite copy exists before retention pruning. Keep the
    same post-write free-space reserve used by the RC0 supervisor so a backup
    cannot consume the headroom that keeps production deployable and healthy.
    """
    reserve_bytes = _runtime_nonnegative_int(
        "CHRISTIANIA_RC0_MIN_FREE_BYTES",
        DEFAULT_BACKUP_MIN_FREE_BYTES,
    )
    reserve_fraction = _runtime_nonnegative_float(
        "CHRISTIANIA_RC0_MIN_FREE_FRACTION",
        DEFAULT_BACKUP_MIN_FREE_FRACTION,
    )
    reserve = max(
        reserve_bytes,
        int(filesystem_total_bytes * reserve_fraction),
    )
    return int(source_size_bytes) + reserve


def plan_backup_capacity(
    *,
    source: Path,
    target_dir: Path,
    retention: int | None = None,
) -> BackupCapacityPlan:
    """Describe whether the next full backup fits after safe retention pruning."""
    keep = (
        retention
        if retention is not None
        else backup_retention_count()
    )
    if keep < 1:
        raise ValueError(
            "Backup retention must be >= 1."
        )

    usage = shutil.disk_usage(
        target_dir
    )
    logical_source = (
        backup_logical_source_bytes(
            source
        )
    )
    required = backup_required_free_bytes(
        source_size_bytes=logical_source,
        filesystem_total_bytes=int(
            usage.total
        ),
    )

    backups = sorted(
        backup_data_files(
            target_dir
        ),
        key=lambda path: (
            path.stat().st_mtime,
            path.name,
        ),
        reverse=True,
    )

    # Preserve TWO existing full recovery points whenever the configured
    # retention target is >=2 and at least two copies exist. Do not sacrifice
    # the second copy BEFORE its successor has passed full verification.
    # Capacity shortage must fail closed rather than silently reducing the
    # operator's redundancy to a single file.
    minimum_preprune_keep = (
        2 if keep >= 2 and len(backups) >= 2 else
        1 if backups else 0
    )
    preprune_keep = min(
        len(backups),
        max(minimum_preprune_keep, keep - 1),
    )

    def reclaimable_bytes(
        retained_count: int,
    ) -> int:
        return sum(
            path.stat().st_size
            for path in backups[
                retained_count:
            ]
        )

    reclaimable = reclaimable_bytes(
        preprune_keep
    )
    projected_free = (
        int(usage.free)
        + reclaimable
    )

    while (
        projected_free < required
        and preprune_keep > minimum_preprune_keep
    ):
        preprune_keep -= 1
        reclaimable = (
            reclaimable_bytes(
                preprune_keep
            )
        )
        projected_free = (
            int(usage.free)
            + reclaimable
        )

    return BackupCapacityPlan(
        filesystem_total_bytes=int(
            usage.total
        ),
        filesystem_free_bytes=int(
            usage.free
        ),
        logical_source_bytes=logical_source,
        required_free_bytes=required,
        retention=keep,
        preprune_keep=preprune_keep,
        current_backup_count=len(
            backups
        ),
        reclaimable_bytes=reclaimable,
        projected_free_bytes=(
            projected_free
        ),
        feasible_after_safe_prune=(
            projected_free
            >= required
        ),
    )


def assert_backup_capacity(
    *,
    source: Path,
    target_dir: Path,
) -> None:
    usage = shutil.disk_usage(target_dir)
    source_bytes = backup_logical_source_bytes(
        source
    )
    required = backup_required_free_bytes(
        source_size_bytes=source_bytes,
        filesystem_total_bytes=int(usage.total),
    )

    if int(usage.free) < required:
        raise RuntimeError(
            "Insufficient backup filesystem headroom: "
            f"free={int(usage.free)} bytes, required={required} bytes, "
            f"logical_source={source_bytes} bytes. "
            "A full temporary backup must fit while preserving the configured "
            "production free-space reserve. No backup file was created."
        )


def _verify_backup(
    path: Path,
    *,
    progress: Callable[[str], None] | None = None,
) -> SqliteVerification:
    return verify_sqlite_snapshot(
        path,
        expected_schema=EXPECTED_SCHEMA_VERSION,
        level="routine",
        progress=progress,
    )


def _vacuum_into_snapshot(
    source: Path,
    destination: Path,
    *,
    progress: Callable[[str], None] | None = None,
) -> None:
    """Take one consistent WAL snapshot without multi-step backup restarts.

    VACUUM INTO uses a single read transaction. Unlike Python's incremental
    Connection.backup(pages=8192), independent daemon lease updates cannot
    reset its progress. Only the temporary destination is ever writable.
    The source is explicitly opened in read-only mode.
    """
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"Snapshot destination already exists: {destination}")
    if BACKUP_SNAPSHOT_TIMEOUT_SECONDS <= 0:
        raise TimeoutError("SQLite snapshot exceeded nonpositive time budget")
    source_uri = source.resolve().as_uri() + "?mode=ro"
    started = time.monotonic()
    last_log = [started]
    timed_out = [False]

    def _progress() -> int:
        now = time.monotonic()
        elapsed = now - started
        if elapsed >= BACKUP_SNAPSHOT_TIMEOUT_SECONDS:
            timed_out[0] = True
            return 1
        if progress is not None and now - last_log[0] >= BACKUP_SNAPSHOT_PROGRESS_INTERVAL_SECONDS:
            progress(f"copy: working elapsed_seconds={elapsed:.0f}")
            last_log[0] = now
        return 0

    conn = sqlite3.connect(source_uri, uri=True, timeout=30.0)
    try:
        conn.execute("PRAGMA busy_timeout=30000")
        conn.set_progress_handler(_progress, 10_000)
        try:
            conn.execute("VACUUM main INTO ?", (str(destination),))
        except sqlite3.OperationalError as exc:
            if timed_out[0]:
                raise TimeoutError(
                    f"SQLite snapshot exceeded {BACKUP_SNAPSHOT_TIMEOUT_SECONDS}s; "
                    "original database and promoted recovery copies are untouched"
                ) from exc
            raise
        finally:
            conn.set_progress_handler(None, 0)
    finally:
        conn.close()
    if not destination.is_file() or destination.stat().st_size <= 0:
        raise RuntimeError("VACUUM INTO produced no usable snapshot")
    # The snapshot must be durable before integrity verification or promotion.
    os.chmod(destination, 0o600)
    with destination.open("r+b") as completed:
        os.fsync(completed.fileno())


def _prune_backups(
    directory: Path,
    *,
    keep: int,
) -> int:
    backups = sorted(
        backup_data_files(directory),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    pruned = 0

    for stale in backups[keep:]:
        stale.unlink()

        if stale.name.endswith(".db.gz"):
            manifest = manifest_path_for(stale)
        else:
            manifest = evidence_path_for(stale)
        if manifest.exists():
            manifest.unlink()

        pruned += 1

    return pruned


def create_verified_backup(
    *,
    db_path: str | Path | None = None,
    backup_dir: str | Path | None = None,
    retention: int | None = None,
    progress: Callable[[str], None] | None = None,
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

    capacity_plan = plan_backup_capacity(
        source=source,
        target_dir=target_dir,
        retention=retention,
    )
    keep = capacity_plan.retention

    if not capacity_plan.feasible_after_safe_prune:
        raise RuntimeError(
            "Insufficient backup filesystem headroom even after all "
            "policy-permitted retention pruning: "
            f"free={capacity_plan.filesystem_free_bytes} bytes, "
            f"safe_prune_reclaimable={capacity_plan.reclaimable_bytes} bytes, "
            f"projected_free={capacity_plan.projected_free_bytes} bytes, "
            f"required={capacity_plan.required_free_bytes} bytes. "
            "Existing verified backups were left untouched."
        )

    # Never pre-delete any recovery point to make room for a new copy.
    # The capacity planner is advisory here: conservative instantaneous
    # headroom must be present without reclaiming any existing backups.
    # Routine verification does not authorize destruction of older deep
    # recovery points, even if their age exceeds the requested retention.
    prepruned = 0
    assert_backup_capacity(
        source=source,
        target_dir=target_dir,
    )

    if progress is not None:
        progress(
            "capacity: passed "
            f"logical_source_bytes={backup_logical_source_bytes(source)} "
            f"main_file_bytes={source.stat().st_size}"
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

    if progress is not None:
        progress(
            "copy: started method=VACUUM_INTO "
            f"source={source} "
            f"temp={temp_path} "
            f"timeout_seconds={BACKUP_SNAPSHOT_TIMEOUT_SECONDS}"
        )

    try:
        # VACUUM INTO reads from one consistent WAL snapshot even if concurrent
        # writers keep committing. The former pages=8192 backup restarted on
        # daemon lease heartbeats, causing unbounded I/O and no progress.
        _vacuum_into_snapshot(source, temp_path, progress=progress)

        if progress is not None:
            progress(
                "copy: completed "
                f"temp_bytes={temp_path.stat().st_size}"
            )

        verification = _verify_backup(temp_path, progress=progress)
        # Full content hash is independent from the bounded SQLite routine
        # verification. Its matching sidecar will be required by compression.
        digest = hash_snapshot(temp_path, progress=progress)
        os.replace(temp_path, final_path)
        publish_plain_evidence(
            final_path, verification, sha256=digest,
        )

        if progress is not None:
            progress(
                "promotion: completed "
                f"path={final_path}"
            )

    except BaseException:
        if temp_path.exists():
            if progress is not None:
                progress(f"cleanup: removing incomplete backup {temp_path}")
            temp_path.unlink()
        # Promotion and evidence publication form a fail-closed pair. Never
        # leave an unmanifested promoted backup from a failed attempt.
        if final_path.exists():
            final_path.unlink()
        evidence = evidence_path_for(final_path)
        if evidence.exists():
            evidence.unlink()
        raise

    # Retention deletion is disabled until a recovery-point-aware policy
    # can prove the replacements and preserve the minimum independent copies.
    # Compression and a separate audited retention job handle capacity;
    # creation itself must never quietly destroy old recovery evidence.
    pruned = prepruned
    if progress is not None:
        progress("retention: protected existing recovery points; pruned=0")

    return BackupResult(
        source_path=str(source),
        backup_path=str(final_path),
        schema_version=verification.schema_version,
        integrity_check=verification.integrity_check,
        foreign_key_violation_count=verification.foreign_key_violation_count,
        pruned_count=pruned,
        verification_level=verification.level,
        quick_check=verification.quick_check,
        source_sha256=digest,
    )
