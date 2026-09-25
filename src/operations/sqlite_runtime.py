from __future__ import annotations

import os
import sqlite3
import shutil
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

from src.config import get_runtime_setting
from src.database.repository import (
    EXPECTED_SCHEMA_VERSION,
    resolve_db_path,
)
from src.operations.backup_compression import (
    backup_data_files,
    manifest_path_for,
)


DEFAULT_BACKUP_RETENTION = 14
DEFAULT_BACKUP_MIN_FREE_BYTES = 15 * 1024**3
DEFAULT_BACKUP_MIN_FREE_FRACTION = 0.15


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
    integrity_check: str
    foreign_key_violation_count: int
    pruned_count: int

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def resolve_backup_dir(
    backup_dir: str | Path | None = None,
) -> Path:
    if backup_dir is not None:
        return Path(backup_dir).expanduser()

    configured = get_runtime_setting(
        "CHRISTIANIA_BACKUP_DIR"
    )

    if configured:
        return Path(configured).expanduser()

    return (
        Path(__file__).resolve().parents[2]
        / "backups"
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


def _install_readonly_compatibility_views(
    connection: sqlite3.Connection,
) -> None:
    """Install connection-local compatibility views for reporting readers.

    Schema v29 keeps the legacy admission table immutable for historical
    evidence and adds a normalized view that UNIONs legacy and intrinsic-risk
    decisions. Older dashboard/read-model SQL still refers to the historical
    table name. A TEMP view with the same unqualified name lets those readonly
    consumers see the normalized decision surface without changing write
    semantics or rewriting historical rows.

    Explicit ``main.shadow_admission_decisions`` continues to address the
    historical table. Databases older than v29 do not contain the normalized
    source view, so this helper is a no-op for release rollback/preflight use.
    """
    normalized = connection.execute(
        """
        SELECT 1
        FROM main.sqlite_master
        WHERE type = 'view'
          AND name = 'v_shadow_admission_decisions_all'
        LIMIT 1;
        """
    ).fetchone()

    if normalized is None:
        return

    connection.execute(
        """
        CREATE TEMP VIEW shadow_admission_decisions AS
        SELECT
            decision_id AS id,
            proposal_id,
            fx_observation_id,
            candidate_id,
            sizing_policy_version,
            cost_model_version,
            cost_provenance,
            proposal_max_loss_usd_minor,
            estimated_cost_usd_minor,
            reserved_risk_usd_minor,
            converted_max_loss_eur_minor,
            estimated_cost_eur_minor,
            reserved_risk_eur_minor,
            bankroll_cap_eur_minor,
            decision,
            reason_code,
            decided_at,
            evidence_json
        FROM main.v_shadow_admission_decisions_all;
        """
    )


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

    # TEMP compatibility objects must be installed before query_only is set.
    # They are connection-local and never alter the persistent database.
    _install_readonly_compatibility_views(
        connection
    )

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

    # Retention is the desired maximum, not a guarantee that may consume the
    # production reserve. Make one normal retention slot when needed, then
    # continue dropping only the oldest backups until the next full verified
    # copy fits. Never pre-delete the newest known-good recovery point.
    if not backups:
        preprune_keep = 0
    else:
        preprune_keep = min(
            len(backups),
            max(
                1,
                keep - 1,
            ),
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
        and preprune_keep > 1
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
) -> tuple[int, str, int]:
    conn = sqlite3.connect(path)

    try:
        version_row = conn.execute(
            '''
            SELECT MAX(version)
            FROM schema_version;
            '''
        ).fetchone()

        if (
            version_row is None
            or version_row[0] is None
        ):
            raise RuntimeError(
                "Backup contains no schema version."
            )

        version = int(version_row[0])

        if progress is not None:
            progress("verification: integrity_check started")

        integrity = str(
            conn.execute(
                "PRAGMA integrity_check;"
            ).fetchone()[0]
        )

        if progress is not None:
            progress(
                "verification: integrity_check completed "
                f"result={integrity}"
            )
            progress(
                "verification: foreign_key_check started"
            )

        fk_rows = conn.execute(
            "PRAGMA foreign_key_check;"
        ).fetchall()

        if progress is not None:
            progress(
                "verification: foreign_key_check completed "
                f"violations={len(fk_rows)}"
            )

    finally:
        conn.close()

    if integrity != "ok":
        raise RuntimeError(
            f"Backup integrity_check failed: {integrity}"
        )

    if fk_rows:
        raise RuntimeError(
            "Backup foreign_key_check returned violations."
        )

    return version, integrity, len(fk_rows)


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

    # A new full backup temporarily coexists with retained recovery points.
    # Capacity planning treats configured retention as a maximum target and
    # may safely retain fewer old copies when disk headroom requires it.
    # The newest known-good normal recovery point is never pre-deleted.
    preprune_keep = (
        capacity_plan.preprune_keep
    )
    prepruned = _prune_backups(
        target_dir,
        keep=preprune_keep,
    )

    if progress is not None and prepruned:
        progress(
            "retention: pre-pruned "
            f"{prepruned} stale backup(s) before capacity check"
        )

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

    source_uri = source.resolve().as_uri() + "?mode=ro"

    source_conn = sqlite3.connect(
        source_uri,
        uri=True,
        timeout=30.0,
    )
    target_conn = sqlite3.connect(
        temp_path
    )

    next_report_fraction = 0.0

    def report_copy(
        status: int,
        remaining: int,
        total: int,
    ) -> None:
        nonlocal next_report_fraction

        if progress is None or total <= 0:
            return

        completed = max(
            0,
            total - remaining,
        )
        fraction = min(
            1.0,
            completed / total,
        )

        if (
            fraction + 1e-12
            < next_report_fraction
            and remaining > 0
        ):
            return

        progress(
            "copy: "
            f"{fraction:.0%} "
            f"pages={completed}/{total} "
            f"status={status}"
        )

        while (
            next_report_fraction
            <= fraction
        ):
            next_report_fraction += 0.10

    if progress is not None:
        progress(
            "copy: started "
            f"source={source} "
            f"temp={temp_path}"
        )

    try:
        try:
            source_conn.backup(
                target_conn,
                pages=8192,
                progress=report_copy,
            )
            target_conn.commit()

            if progress is not None:
                progress(
                    "copy: completed "
                    f"temp_bytes={temp_path.stat().st_size}"
                )
        finally:
            target_conn.close()
            source_conn.close()

        version, integrity, fk_count = (
            _verify_backup(
                temp_path,
                progress=progress,
            )
        )

        if version != EXPECTED_SCHEMA_VERSION:
            raise RuntimeError(
                f"Backup schema v{version} does not match "
                f"expected v{EXPECTED_SCHEMA_VERSION}."
            )

        os.replace(
            temp_path,
            final_path,
        )

        if progress is not None:
            progress(
                "promotion: completed "
                f"path={final_path}"
            )

    except BaseException:
        if temp_path.exists():
            if progress is not None:
                progress(
                    "cleanup: removing incomplete temp backup "
                    f"path={temp_path}"
                )
            temp_path.unlink()
        raise

    pruned = prepruned + _prune_backups(
        target_dir,
        keep=keep,
    )

    if progress is not None:
        progress(
            "retention: completed "
            f"pruned={pruned}"
        )

    return BackupResult(
        source_path=str(source),
        backup_path=str(final_path),
        schema_version=version,
        integrity_check=integrity,
        foreign_key_violation_count=fk_count,
        pruned_count=pruned,
    )
