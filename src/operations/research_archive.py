from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

from src.config import get_runtime_setting
from src.database.repository import (
    EXPECTED_SCHEMA_VERSION,
    resolve_db_path,
)


ARCHIVE_FORMAT_VERSION = 1
ARCHIVE_COVERAGE = "HIGH_VOLUME_RESEARCH_EVIDENCE_V1"
DEFAULT_KEEP_HOT_COMPLETED_RUNS = 50
DEFAULT_ARCHIVE_MIN_FREE_BYTES = 15 * 1024**3
CHUNK_SIZE = 1024 * 1024

_SESSION_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SAFE_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class ArchiveTableSpec:
    table_name: str
    select_sql: str


ARCHIVE_TABLE_SPECS: tuple[ArchiveTableSpec, ...] = (
    ArchiveTableSpec(
        "research_runs",
        """
        SELECT t.*
        FROM source.research_runs AS t
        JOIN _archive_runs AS ar
          ON ar.id = t.id
        """,
    ),
    ArchiveTableSpec(
        "research_daemon_iterations",
        """
        SELECT t.*
        FROM source.research_daemon_iterations AS t
        JOIN _archive_runs AS ar
          ON ar.id = t.research_run_id
        """,
    ),
    ArchiveTableSpec(
        "market_snapshots",
        """
        SELECT t.*
        FROM source.market_snapshots AS t
        JOIN _archive_runs AS ar
          ON ar.id = t.research_run_id
        """,
    ),
    ArchiveTableSpec(
        "option_quotes",
        """
        SELECT t.*
        FROM source.option_quotes AS t
        JOIN source.market_snapshots AS ms
          ON ms.id = t.snapshot_id
        JOIN _archive_runs AS ar
          ON ar.id = ms.research_run_id
        """,
    ),
    ArchiveTableSpec(
        "provider_model_observations",
        """
        SELECT t.*
        FROM source.provider_model_observations AS t
        JOIN source.option_quotes AS oq
          ON oq.id = t.option_quote_id
        JOIN source.market_snapshots AS ms
          ON ms.id = oq.snapshot_id
        JOIN _archive_runs AS ar
          ON ar.id = ms.research_run_id
        """,
    ),
    ArchiveTableSpec(
        "listing_reference_contracts",
        """
        SELECT t.*
        FROM source.listing_reference_contracts AS t
        JOIN _archive_runs AS ar
          ON ar.id = t.research_run_id
        """,
    ),
    ArchiveTableSpec(
        "provider_observation_availability",
        """
        SELECT t.*
        FROM source.provider_observation_availability AS t
        JOIN source.listing_reference_contracts AS lrc
          ON lrc.id = t.reference_contract_id
        JOIN _archive_runs AS ar
          ON ar.id = lrc.research_run_id
        """,
    ),
    ArchiveTableSpec(
        "hypothesis_scanner_runs",
        """
        SELECT t.*
        FROM source.hypothesis_scanner_runs AS t
        JOIN _archive_runs AS ar
          ON ar.id = t.research_run_id
        """,
    ),
    ArchiveTableSpec(
        "hypothesis_scanner_evaluations",
        """
        SELECT t.*
        FROM source.hypothesis_scanner_evaluations AS t
        JOIN source.hypothesis_scanner_runs AS r
          ON r.id = t.scanner_run_id
        JOIN _archive_runs AS ar
          ON ar.id = r.research_run_id
        """,
    ),
    ArchiveTableSpec(
        "local_surface_residual_v2_runs",
        """
        SELECT t.*
        FROM source.local_surface_residual_v2_runs AS t
        JOIN _archive_runs AS ar
          ON ar.id = t.research_run_id
        """,
    ),
    ArchiveTableSpec(
        "local_surface_residual_v2_observations",
        """
        SELECT t.*
        FROM source.local_surface_residual_v2_observations AS t
        JOIN source.local_surface_residual_v2_runs AS r
          ON r.id = t.model_run_id
        JOIN _archive_runs AS ar
          ON ar.id = r.research_run_id
        """,
    ),
)


ARCHIVED_RUN_COUNT_SQL: dict[str, str] = {
    "research_runs": """
        SELECT COUNT(*)
        FROM research_runs
        WHERE id = ?;
    """,
    "research_daemon_iterations": """
        SELECT COUNT(*)
        FROM research_daemon_iterations
        WHERE research_run_id = ?;
    """,
    "market_snapshots": """
        SELECT COUNT(*)
        FROM market_snapshots
        WHERE research_run_id = ?;
    """,
    "option_quotes": """
        SELECT COUNT(*)
        FROM option_quotes AS oq
        JOIN market_snapshots AS ms
          ON ms.id = oq.snapshot_id
        WHERE ms.research_run_id = ?;
    """,
    "provider_model_observations": """
        SELECT COUNT(*)
        FROM provider_model_observations AS pmo
        JOIN option_quotes AS oq
          ON oq.id = pmo.option_quote_id
        JOIN market_snapshots AS ms
          ON ms.id = oq.snapshot_id
        WHERE ms.research_run_id = ?;
    """,
    "listing_reference_contracts": """
        SELECT COUNT(*)
        FROM listing_reference_contracts
        WHERE research_run_id = ?;
    """,
    "provider_observation_availability": """
        SELECT COUNT(*)
        FROM provider_observation_availability AS poa
        JOIN listing_reference_contracts AS lrc
          ON lrc.id = poa.reference_contract_id
        WHERE lrc.research_run_id = ?;
    """,
    "hypothesis_scanner_runs": """
        SELECT COUNT(*)
        FROM hypothesis_scanner_runs
        WHERE research_run_id = ?;
    """,
    "hypothesis_scanner_evaluations": """
        SELECT COUNT(*)
        FROM hypothesis_scanner_evaluations AS e
        JOIN hypothesis_scanner_runs AS r
          ON r.id = e.scanner_run_id
        WHERE r.research_run_id = ?;
    """,
    "local_surface_residual_v2_runs": """
        SELECT COUNT(*)
        FROM local_surface_residual_v2_runs
        WHERE research_run_id = ?;
    """,
    "local_surface_residual_v2_observations": """
        SELECT COUNT(*)
        FROM local_surface_residual_v2_observations AS o
        JOIN local_surface_residual_v2_runs AS r
          ON r.id = o.model_run_id
        WHERE r.research_run_id = ?;
    """,
}


@dataclass(frozen=True)
class ArchiveSessionCandidate:
    session_date: str
    run_ids: tuple[int, ...]
    min_run_id: int
    max_run_id: int
    terminal_run_count: int
    completed_run_count: int
    already_archived: bool
    eligible: bool
    reason: str

    def as_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["run_ids"] = list(self.run_ids)
        return data


@dataclass(frozen=True)
class ResearchArchiveManifest:
    format_version: int
    coverage: str
    created_at: str
    session_date: str
    run_ids: tuple[int, ...]
    min_run_id: int
    max_run_id: int
    source_schema_version: int
    source_db_size_bytes: int
    table_counts: dict[str, int]
    uncompressed_size_bytes: int
    compressed_size_bytes: int
    uncompressed_sha256: str
    compressed_sha256: str
    compression: str
    archive_filename: str
    manifest_filename: str
    integrity_check: str
    prune_eligible: bool
    prune_block_reason: str

    def as_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["run_ids"] = list(self.run_ids)
        return data


@dataclass(frozen=True)
class ArchiveInventory:
    directory: str
    archive_count: int
    manifests: tuple[ResearchArchiveManifest, ...]
    invalid_manifests: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "directory": self.directory,
            "archive_count": self.archive_count,
            "manifests": [
                manifest.as_dict()
                for manifest in self.manifests
            ],
            "invalid_manifests": list(
                self.invalid_manifests
            ),
        }


@dataclass(frozen=True)
class ArchivedRunEvidence:
    run_id: int
    session_date: str
    archive_filename: str
    table_counts: dict[str, int]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ArchiveMaintenanceResult:
    archived_count: int
    archived_sessions: tuple[str, ...]
    skipped_sessions: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "archived_count": self.archived_count,
            "archived_sessions": list(
                self.archived_sessions
            ),
            "skipped_sessions": list(
                self.skipped_sessions
            ),
        }


def resolve_archive_dir(
    archive_dir: str | Path | None = None,
) -> Path:
    if archive_dir is not None:
        return Path(archive_dir).expanduser()

    configured = get_runtime_setting(
        "CHRISTIANIA_EVIDENCE_ARCHIVE_DIR"
    )
    if configured:
        return Path(configured).expanduser()

    return (
        Path(__file__).resolve().parents[2]
        / "evidence-archives"
    )


def keep_hot_completed_runs() -> int:
    configured = get_runtime_setting(
        "CHRISTIANIA_EVIDENCE_KEEP_HOT_COMPLETED_RUNS"
    )
    if configured in (None, ""):
        return DEFAULT_KEEP_HOT_COMPLETED_RUNS

    value = int(configured)
    if value < 1:
        raise ValueError(
            "CHRISTIANIA_EVIDENCE_KEEP_HOT_COMPLETED_RUNS "
            "must be >= 1."
        )
    return value


def _archive_min_free_bytes() -> int:
    configured = get_runtime_setting(
        "CHRISTIANIA_EVIDENCE_ARCHIVE_MIN_FREE_BYTES"
    )
    if configured in (None, ""):
        return DEFAULT_ARCHIVE_MIN_FREE_BYTES

    value = int(configured)
    if value < 0:
        raise ValueError(
            "CHRISTIANIA_EVIDENCE_ARCHIVE_MIN_FREE_BYTES "
            "cannot be negative."
        )
    return value


def _quote_identifier(value: str) -> str:
    if not _SAFE_IDENTIFIER_RE.fullmatch(value):
        raise ValueError(
            f"Unsafe SQLite identifier: {value!r}"
        )
    return '"' + value + '"'


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_gzip_payload(path: Path) -> str:
    digest = hashlib.sha256()
    with gzip.open(path, "rb") as handle:
        while True:
            chunk = handle.read(CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _fsync_directory(directory: Path) -> None:
    if os.name == "nt":
        return

    flags = os.O_RDONLY | getattr(
        os,
        "O_DIRECTORY",
        0,
    )
    fd = os.open(directory, flags)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_json_atomic(
    path: Path,
    payload: dict[str, object],
) -> None:
    temp = path.with_name(
        f".{path.name}.{os.getpid()}.tmp"
    )
    text = (
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )

    try:
        with temp.open(
            "w",
            encoding="utf-8",
            newline="\n",
        ) as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())

        os.replace(temp, path)
        _fsync_directory(path.parent)
    finally:
        if temp.exists():
            temp.unlink()


def _manifest_from_dict(
    payload: dict[str, object],
) -> ResearchArchiveManifest:
    return ResearchArchiveManifest(
        format_version=int(payload["format_version"]),
        coverage=str(payload["coverage"]),
        created_at=str(payload["created_at"]),
        session_date=str(payload["session_date"]),
        run_ids=tuple(
            int(value)
            for value in payload["run_ids"]
        ),
        min_run_id=int(payload["min_run_id"]),
        max_run_id=int(payload["max_run_id"]),
        source_schema_version=int(
            payload["source_schema_version"]
        ),
        source_db_size_bytes=int(
            payload["source_db_size_bytes"]
        ),
        table_counts={
            str(key): int(value)
            for key, value in dict(
                payload["table_counts"]
            ).items()
        },
        uncompressed_size_bytes=int(
            payload["uncompressed_size_bytes"]
        ),
        compressed_size_bytes=int(
            payload["compressed_size_bytes"]
        ),
        uncompressed_sha256=str(
            payload["uncompressed_sha256"]
        ),
        compressed_sha256=str(
            payload["compressed_sha256"]
        ),
        compression=str(payload["compression"]),
        archive_filename=str(
            payload["archive_filename"]
        ),
        manifest_filename=str(
            payload["manifest_filename"]
        ),
        integrity_check=str(
            payload["integrity_check"]
        ),
        prune_eligible=bool(
            payload["prune_eligible"]
        ),
        prune_block_reason=str(
            payload["prune_block_reason"]
        ),
    )


def load_archive_manifest(
    path: str | Path,
) -> ResearchArchiveManifest:
    manifest_path = Path(path).expanduser()
    payload = json.loads(
        manifest_path.read_text(
            encoding="utf-8"
        )
    )
    manifest = _manifest_from_dict(payload)

    if manifest.format_version != ARCHIVE_FORMAT_VERSION:
        raise RuntimeError(
            "Unsupported Christiania research archive "
            f"format v{manifest.format_version}."
        )
    if manifest.coverage != ARCHIVE_COVERAGE:
        raise RuntimeError(
            "Unexpected research archive coverage: "
            f"{manifest.coverage}"
        )
    if manifest.manifest_filename != manifest_path.name:
        raise RuntimeError(
            "Research archive manifest filename mismatch."
        )
    if not manifest.run_ids:
        raise RuntimeError(
            "Research archive manifest contains no run IDs."
        )
    if (
        min(manifest.run_ids) != manifest.min_run_id
        or max(manifest.run_ids) != manifest.max_run_id
    ):
        raise RuntimeError(
            "Research archive run bounds do not match run IDs."
        )

    return manifest


def inventory_research_archives(
    archive_dir: str | Path | None = None,
) -> ArchiveInventory:
    directory = resolve_archive_dir(
        archive_dir
    )
    if not directory.exists():
        return ArchiveInventory(
            directory=str(directory),
            archive_count=0,
            manifests=(),
            invalid_manifests=(),
        )

    manifests: list[
        ResearchArchiveManifest
    ] = []
    invalid: list[str] = []

    for path in sorted(
        directory.glob(
            "research_evidence_*.manifest.json"
        )
    ):
        try:
            manifest = load_archive_manifest(
                path
            )
            archive_path = (
                directory
                / manifest.archive_filename
            )
            if not archive_path.is_file():
                raise FileNotFoundError(
                    f"Archive payload missing: {archive_path}"
                )
            if (
                archive_path.stat().st_size
                != manifest.compressed_size_bytes
            ):
                raise RuntimeError(
                    "Archive payload size does not match manifest."
                )
            manifests.append(manifest)
        except Exception as exc:
            invalid.append(
                f"{path}:{type(exc).__name__}:{exc}"
            )

    manifests.sort(
        key=lambda item: (
            item.session_date,
            item.min_run_id,
        )
    )

    return ArchiveInventory(
        directory=str(directory),
        archive_count=len(manifests),
        manifests=tuple(manifests),
        invalid_manifests=tuple(invalid),
    )


def _archived_session_dates(
    archive_dir: Path,
) -> set[str]:
    inventory = inventory_research_archives(
        archive_dir
    )
    return {
        item.session_date
        for item in inventory.manifests
    }


def plan_archive_sessions(
    *,
    db_path: str | Path | None = None,
    archive_dir: str | Path | None = None,
    keep_hot_runs: int | None = None,
) -> tuple[ArchiveSessionCandidate, ...]:
    database = resolve_db_path(db_path)
    directory = resolve_archive_dir(
        archive_dir
    )
    keep = (
        keep_hot_completed_runs()
        if keep_hot_runs is None
        else int(keep_hot_runs)
    )
    if keep < 1:
        raise ValueError(
            "keep_hot_runs must be >= 1."
        )

    uri = database.resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(
        uri,
        uri=True,
        timeout=30.0,
    )
    conn.row_factory = sqlite3.Row

    try:
        completed_rows = conn.execute(
            """
            SELECT id
            FROM research_runs
            WHERE status = 'COMPLETED'
            ORDER BY id DESC
            LIMIT ?;
            """,
            (keep,),
        ).fetchall()

        if len(completed_rows) < keep:
            hot_floor = None
        else:
            hot_floor = min(
                int(row["id"])
                for row in completed_rows
            )

        rows = conn.execute(
            """
            SELECT
                us_session_date,
                MIN(id) AS min_run_id,
                MAX(id) AS max_run_id,
                COUNT(*) AS run_count,
                SUM(
                    CASE
                        WHEN status = 'COMPLETED'
                        THEN 1
                        ELSE 0
                    END
                ) AS completed_count,
                SUM(
                    CASE
                        WHEN status IN (
                            'STARTED',
                            'COLLECTING'
                        )
                        THEN 1
                        ELSE 0
                    END
                ) AS nonterminal_count
            FROM research_runs
            WHERE us_session_date IS NOT NULL
            GROUP BY us_session_date
            ORDER BY us_session_date;
            """
        ).fetchall()

        archived_dates = _archived_session_dates(
            directory
        )
        candidates: list[
            ArchiveSessionCandidate
        ] = []

        for row in rows:
            session_date = str(
                row["us_session_date"]
            )
            run_rows = conn.execute(
                """
                SELECT id
                FROM research_runs
                WHERE us_session_date = ?
                  AND status IN (
                      'COMPLETED',
                      'FAILED',
                      'INVALID'
                  )
                ORDER BY id;
                """,
                (session_date,),
            ).fetchall()
            run_ids = tuple(
                int(item["id"])
                for item in run_rows
            )
            already = (
                session_date in archived_dates
            )
            nonterminal = int(
                row["nonterminal_count"] or 0
            )
            max_run_id = int(
                row["max_run_id"]
            )

            if already:
                eligible = False
                reason = "ALREADY_ARCHIVED"
            elif nonterminal:
                eligible = False
                reason = "SESSION_HAS_NONTERMINAL_RUNS"
            elif not run_ids:
                eligible = False
                reason = "NO_TERMINAL_RUNS"
            elif hot_floor is None:
                eligible = False
                reason = "HOT_RETENTION_NOT_YET_FILLED"
            elif max_run_id >= hot_floor:
                eligible = False
                reason = "WITHIN_HOT_RUN_WINDOW"
            else:
                eligible = True
                reason = "ELIGIBLE"

            candidates.append(
                ArchiveSessionCandidate(
                    session_date=session_date,
                    run_ids=run_ids,
                    min_run_id=int(
                        row["min_run_id"]
                    ),
                    max_run_id=max_run_id,
                    terminal_run_count=len(
                        run_ids
                    ),
                    completed_run_count=int(
                        row["completed_count"] or 0
                    ),
                    already_archived=already,
                    eligible=eligible,
                    reason=reason,
                )
            )

        return tuple(candidates)
    finally:
        conn.close()


def _candidate_for_session(
    session_date: str,
    *,
    db_path: str | Path | None,
    archive_dir: Path,
    keep_hot_runs: int,
) -> ArchiveSessionCandidate:
    for candidate in plan_archive_sessions(
        db_path=db_path,
        archive_dir=archive_dir,
        keep_hot_runs=keep_hot_runs,
    ):
        if candidate.session_date == session_date:
            return candidate

    raise ValueError(
        "No Christiania research session exists for "
        f"{session_date}."
    )


def _assert_capacity(
    *,
    source: Path,
    archive_dir: Path,
    run_count: int,
    total_completed_runs: int,
) -> None:
    usage = shutil.disk_usage(
        archive_dir
    )
    reserve = _archive_min_free_bytes()

    denominator = max(
        1,
        total_completed_runs,
    )
    proportional = int(
        source.stat().st_size
        * run_count
        / denominator
        * 1.75
    )
    estimated_archive = max(
        512 * 1024**2,
        proportional,
    )
    required = reserve + estimated_archive

    if int(usage.free) < required:
        raise RuntimeError(
            "Insufficient headroom for research archive: "
            f"free={int(usage.free)} bytes, "
            f"required={required} bytes, "
            f"reserve={reserve} bytes, "
            f"estimated_archive={estimated_archive} bytes."
        )


def _table_exists(
    connection: sqlite3.Connection,
    table_name: str,
) -> bool:
    row = connection.execute(
        """
        SELECT 1
        FROM source.sqlite_master
        WHERE type = 'table'
          AND name = ?
        LIMIT 1;
        """,
        (table_name,),
    ).fetchone()
    return row is not None


def create_research_archive(
    session_date: str,
    *,
    db_path: str | Path | None = None,
    archive_dir: str | Path | None = None,
    keep_hot_runs: int | None = None,
    progress: Callable[[str], None] | None = None,
) -> ResearchArchiveManifest:
    if not _SESSION_DATE_RE.fullmatch(
        session_date
    ):
        raise ValueError(
            "session_date must use YYYY-MM-DD."
        )

    source = resolve_db_path(db_path)
    directory = resolve_archive_dir(
        archive_dir
    )
    directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    keep = (
        keep_hot_completed_runs()
        if keep_hot_runs is None
        else int(keep_hot_runs)
    )
    if keep < 1:
        raise ValueError(
            "keep_hot_runs must be >= 1."
        )

    candidate = _candidate_for_session(
        session_date,
        db_path=db_path,
        archive_dir=directory,
        keep_hot_runs=keep,
    )
    if not candidate.eligible:
        raise RuntimeError(
            "Research session is not archive eligible: "
            f"{candidate.reason}"
        )

    archive_stem = (
        f"research_evidence_{session_date}"
        f"_runs_{candidate.min_run_id}"
        f"_{candidate.max_run_id}"
    )
    final_gzip = directory / (
        archive_stem + ".db.gz"
    )
    manifest_path = directory / (
        archive_stem + ".manifest.json"
    )
    temp_db = directory / (
        "." + archive_stem + ".db.tmp"
    )
    temp_gzip = directory / (
        "." + archive_stem + ".db.gz.tmp"
    )

    for path in (
        final_gzip,
        manifest_path,
        temp_db,
        temp_gzip,
    ):
        if path.exists():
            raise FileExistsError(
                f"Research archive target already exists: {path}"
            )

    source_uri = (
        source.resolve().as_uri()
        + "?mode=ro"
    )
    connection = sqlite3.connect(
        ":memory:",
        uri=True,
        timeout=30.0,
        isolation_level=None,
    )

    try:
        connection.execute(
            "ATTACH DATABASE ? AS source;",
            (source_uri,),
        )
        connection.execute(
            "ATTACH DATABASE ? AS archive;",
            (str(temp_db),),
        )
        connection.execute(
            """
            CREATE TEMP TABLE _archive_runs (
                id INTEGER PRIMARY KEY
            );
            """
        )
        connection.executemany(
            """
            INSERT INTO _archive_runs(id)
            VALUES(?);
            """,
            (
                (run_id,)
                for run_id in candidate.run_ids
            ),
        )

        schema_row = connection.execute(
            """
            SELECT MAX(version)
            FROM source.schema_version;
            """
        ).fetchone()
        if (
            schema_row is None
            or schema_row[0] is None
        ):
            raise RuntimeError(
                "Source database contains no schema version."
            )
        schema_version = int(
            schema_row[0]
        )
        if schema_version != EXPECTED_SCHEMA_VERSION:
            raise RuntimeError(
                "Source schema does not match active release: "
                f"v{schema_version} != "
                f"v{EXPECTED_SCHEMA_VERSION}."
            )

        total_completed = int(
            connection.execute(
                """
                SELECT COUNT(*)
                FROM source.research_runs
                WHERE status = 'COMPLETED';
                """
            ).fetchone()[0]
        )
        _assert_capacity(
            source=source,
            archive_dir=directory,
            run_count=len(
                candidate.run_ids
            ),
            total_completed_runs=total_completed,
        )

        if progress is not None:
            progress(
                "extract: started "
                f"session={session_date} "
                f"runs={len(candidate.run_ids)}"
            )

        connection.execute("BEGIN;")
        connection.execute(
            """
            CREATE TABLE archive.archive_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )
        connection.execute(
            """
            CREATE TABLE archive.archive_row_counts (
                table_name TEXT PRIMARY KEY,
                row_count INTEGER NOT NULL
            );
            """
        )

        created_at = (
            datetime.now(UTC)
            .isoformat()
            .replace("+00:00", "Z")
        )
        metadata = {
            "format_version": str(
                ARCHIVE_FORMAT_VERSION
            ),
            "coverage": ARCHIVE_COVERAGE,
            "session_date": session_date,
            "run_ids_json": json.dumps(
                list(candidate.run_ids),
                separators=(",", ":"),
            ),
            "source_schema_version": str(
                schema_version
            ),
            "created_at": created_at,
        }
        connection.executemany(
            """
            INSERT INTO archive.archive_metadata(
                key,
                value
            )
            VALUES(?, ?);
            """,
            metadata.items(),
        )

        table_counts: dict[
            str,
            int,
        ] = {}

        for spec in ARCHIVE_TABLE_SPECS:
            if not _table_exists(
                connection,
                spec.table_name,
            ):
                raise RuntimeError(
                    "Required archive source table missing: "
                    f"{spec.table_name}"
                )

            quoted = _quote_identifier(
                spec.table_name
            )
            connection.execute(
                f"""
                CREATE TABLE archive.{quoted}
                AS
                SELECT *
                FROM source.{quoted}
                WHERE 0;
                """
            )

            source_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM ("
                    + spec.select_sql
                    + ");"
                ).fetchone()[0]
            )
            connection.execute(
                f"""
                INSERT INTO archive.{quoted}
                {spec.select_sql};
                """
            )
            archive_count = int(
                connection.execute(
                    f"""
                    SELECT COUNT(*)
                    FROM archive.{quoted};
                    """
                ).fetchone()[0]
            )
            if archive_count != source_count:
                raise RuntimeError(
                    "Research archive row-count mismatch "
                    f"for {spec.table_name}: "
                    f"source={source_count}, "
                    f"archive={archive_count}."
                )

            table_counts[
                spec.table_name
            ] = archive_count
            connection.execute(
                """
                INSERT INTO archive.archive_row_counts(
                    table_name,
                    row_count
                )
                VALUES(?, ?);
                """,
                (
                    spec.table_name,
                    archive_count,
                ),
            )

            if progress is not None:
                progress(
                    "extract: "
                    f"{spec.table_name}="
                    f"{archive_count}"
                )

        connection.commit()

        integrity = str(
            connection.execute(
                """
                PRAGMA archive.integrity_check;
                """
            ).fetchone()[0]
        )
        if integrity != "ok":
            raise RuntimeError(
                "Research archive integrity_check failed: "
                f"{integrity}"
            )

        connection.execute(
            "DETACH DATABASE archive;"
        )
        connection.execute(
            "DETACH DATABASE source;"
        )

    except BaseException:
        try:
            connection.rollback()
        except sqlite3.Error:
            pass
        raise
    finally:
        connection.close()

    try:
        if progress is not None:
            progress(
                "verify: sqlite integrity_check=ok"
            )

        uncompressed_size = (
            temp_db.stat().st_size
        )
        uncompressed_sha = _sha256_file(
            temp_db
        )

        if progress is not None:
            progress(
                "compress: started "
                f"bytes={uncompressed_size}"
            )

        with temp_db.open("rb") as src:
            with temp_gzip.open("wb") as raw:
                with gzip.GzipFile(
                    filename="",
                    mode="wb",
                    compresslevel=6,
                    fileobj=raw,
                    mtime=0,
                ) as gz:
                    shutil.copyfileobj(
                        src,
                        gz,
                        length=CHUNK_SIZE,
                    )
                raw.flush()
                os.fsync(raw.fileno())

        payload_sha = _sha256_gzip_payload(
            temp_gzip
        )
        if payload_sha != uncompressed_sha:
            raise RuntimeError(
                "Research archive compressed payload "
                "does not match source archive SHA-256."
            )

        compressed_sha = _sha256_file(
            temp_gzip
        )
        compressed_size = (
            temp_gzip.stat().st_size
        )

        os.replace(
            temp_gzip,
            final_gzip,
        )
        _fsync_directory(directory)

        manifest = ResearchArchiveManifest(
            format_version=ARCHIVE_FORMAT_VERSION,
            coverage=ARCHIVE_COVERAGE,
            created_at=created_at,
            session_date=session_date,
            run_ids=candidate.run_ids,
            min_run_id=candidate.min_run_id,
            max_run_id=candidate.max_run_id,
            source_schema_version=schema_version,
            source_db_size_bytes=source.stat().st_size,
            table_counts=table_counts,
            uncompressed_size_bytes=uncompressed_size,
            compressed_size_bytes=compressed_size,
            uncompressed_sha256=uncompressed_sha,
            compressed_sha256=compressed_sha,
            compression="gzip",
            archive_filename=final_gzip.name,
            manifest_filename=manifest_path.name,
            integrity_check="ok",
            prune_eligible=False,
            prune_block_reason=(
                "OFFHOST_IMMUTABLE_COPY_NOT_CONFIRMED"
            ),
        )
        _write_json_atomic(
            manifest_path,
            manifest.as_dict(),
        )

        verify_research_archive(
            manifest_path,
            deep_payload=True,
        )

        temp_db.unlink()
        _fsync_directory(directory)

        if progress is not None:
            progress(
                "archive: promoted "
                f"path={final_gzip} "
                f"compressed_bytes={compressed_size}"
            )

        return manifest

    except BaseException:
        if temp_gzip.exists():
            temp_gzip.unlink()
        if temp_db.exists():
            temp_db.unlink()
        if final_gzip.exists():
            final_gzip.unlink()
        if manifest_path.exists():
            manifest_path.unlink()
        raise


def verify_materialized_archive_contract(
    conn: sqlite3.Connection,
    manifest: ResearchArchiveManifest,
) -> None:
    metadata_rows = conn.execute(
        """
        SELECT key, value
        FROM archive_metadata;
        """
    ).fetchall()

    metadata = {
        str(key): str(value)
        for key, value
        in metadata_rows
    }

    required_metadata = {
        "format_version":
            str(manifest.format_version),
        "coverage":
            manifest.coverage,
        "session_date":
            manifest.session_date,
        "source_schema_version":
            str(
                manifest.source_schema_version
            ),
        "created_at":
            manifest.created_at,
    }

    for key, expected in required_metadata.items():
        actual = metadata.get(
            key
        )
        if actual != expected:
            raise RuntimeError(
                "Research archive internal metadata "
                f"mismatch for {key}: "
                f"{actual!r} != {expected!r}."
            )

    try:
        internal_run_ids = tuple(
            int(run_id)
            for run_id
            in json.loads(
                metadata[
                    "run_ids_json"
                ]
            )
        )
    except (
        KeyError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        raise RuntimeError(
            "Research archive internal run_ids_json "
            "is missing or invalid."
        ) from exc

    if (
        internal_run_ids
        != manifest.run_ids
    ):
        raise RuntimeError(
            "Research archive internal run IDs do "
            "not match the manifest."
        )

    internal_counts = {
        str(table_name):
            int(row_count)
        for (
            table_name,
            row_count,
        ) in conn.execute(
            """
            SELECT table_name, row_count
            FROM archive_row_counts;
            """
        ).fetchall()
    }

    if (
        internal_counts
        != manifest.table_counts
    ):
        raise RuntimeError(
            "Research archive internal row-count "
            "metadata does not match the manifest."
        )


def verify_research_archive(
    manifest_path: str | Path,
    *,
    deep_payload: bool = False,
) -> ResearchArchiveManifest:
    path = Path(
        manifest_path
    ).expanduser()
    manifest = load_archive_manifest(path)
    archive_path = (
        path.parent
        / manifest.archive_filename
    )

    if not archive_path.is_file():
        raise FileNotFoundError(
            f"Research archive payload missing: {archive_path}"
        )
    if (
        archive_path.stat().st_size
        != manifest.compressed_size_bytes
    ):
        raise RuntimeError(
            "Research archive compressed size mismatch."
        )

    compressed_sha = _sha256_file(
        archive_path
    )
    if (
        compressed_sha
        != manifest.compressed_sha256
    ):
        raise RuntimeError(
            "Research archive compressed SHA-256 mismatch."
        )

    if not deep_payload:
        return manifest

    payload_sha = _sha256_gzip_payload(
        archive_path
    )
    if (
        payload_sha
        != manifest.uncompressed_sha256
    ):
        raise RuntimeError(
            "Research archive payload SHA-256 mismatch."
        )

    with tempfile.TemporaryDirectory(
        prefix="christiania-research-archive-"
    ) as temp_dir:
        restored = (
            Path(temp_dir)
            / "archive.db"
        )
        with gzip.open(
            archive_path,
            "rb",
        ) as src:
            with restored.open(
                "wb"
            ) as dst:
                shutil.copyfileobj(
                    src,
                    dst,
                    length=CHUNK_SIZE,
                )

        if (
            restored.stat().st_size
            != manifest.uncompressed_size_bytes
        ):
            raise RuntimeError(
                "Restored research archive size mismatch."
            )

        uri = (
            restored.resolve().as_uri()
            + "?mode=ro"
        )
        conn = sqlite3.connect(
            uri,
            uri=True,
            timeout=30.0,
        )
        try:
            integrity = str(
                conn.execute(
                    "PRAGMA integrity_check;"
                ).fetchone()[0]
            )
            if integrity != "ok":
                raise RuntimeError(
                    "Restored research archive "
                    f"integrity_check failed: {integrity}"
                )

            verify_materialized_archive_contract(
                conn,
                manifest,
            )

            for (
                table_name,
                expected_count,
            ) in manifest.table_counts.items():
                quoted = _quote_identifier(
                    table_name
                )
                actual = int(
                    conn.execute(
                        f"""
                        SELECT COUNT(*)
                        FROM {quoted};
                        """
                    ).fetchone()[0]
                )
                if actual != expected_count:
                    raise RuntimeError(
                        "Restored research archive "
                        "row-count mismatch for "
                        f"{table_name}: "
                        f"{actual} != "
                        f"{expected_count}."
                    )
        finally:
            conn.close()

    return manifest


def find_archive_for_run(
    run_id: int,
    *,
    archive_dir: str | Path | None = None,
) -> ResearchArchiveManifest | None:
    target = int(run_id)
    inventory = inventory_research_archives(
        archive_dir
    )
    for manifest in inventory.manifests:
        if target in manifest.run_ids:
            return manifest
    return None


def read_archived_run_evidence(
    run_id: int,
    *,
    archive_dir: str | Path | None = None,
) -> ArchivedRunEvidence:
    target_run = int(run_id)
    directory = resolve_archive_dir(
        archive_dir
    )
    manifest = find_archive_for_run(
        target_run,
        archive_dir=directory,
    )
    if manifest is None:
        raise FileNotFoundError(
            "No verified Christiania research archive "
            f"contains run {target_run}."
        )

    manifest_path = (
        directory
        / manifest.manifest_filename
    )
    verify_research_archive(
        manifest_path,
        deep_payload=False,
    )
    archive_path = (
        directory
        / manifest.archive_filename
    )

    with tempfile.TemporaryDirectory(
        prefix="christiania-archive-read-"
    ) as temp_dir:
        restored = (
            Path(temp_dir)
            / "archive.db"
        )
        digest = hashlib.sha256()
        with gzip.open(
            archive_path,
            "rb",
        ) as src:
            with restored.open(
                "wb"
            ) as dst:
                while True:
                    chunk = src.read(
                        CHUNK_SIZE
                    )
                    if not chunk:
                        break
                    digest.update(chunk)
                    dst.write(chunk)

        if (
            digest.hexdigest()
            != manifest.uncompressed_sha256
        ):
            raise RuntimeError(
                "Archived run read-through payload "
                "SHA-256 mismatch."
            )

        uri = (
            restored.resolve().as_uri()
            + "?mode=ro"
        )
        conn = sqlite3.connect(
            uri,
            uri=True,
            timeout=30.0,
        )
        try:
            verify_materialized_archive_contract(
                conn,
                manifest,
            )

            exists = conn.execute(
                """
                SELECT 1
                FROM research_runs
                WHERE id = ?
                LIMIT 1;
                """,
                (target_run,),
            ).fetchone()
            if exists is None:
                raise RuntimeError(
                    "Archive manifest claims run "
                    f"{target_run}, but archive payload "
                    "does not contain it."
                )

            counts = {
                table_name: int(
                    conn.execute(
                        sql,
                        (target_run,),
                    ).fetchone()[0]
                )
                for table_name, sql
                in ARCHIVED_RUN_COUNT_SQL.items()
            }
        finally:
            conn.close()

    return ArchivedRunEvidence(
        run_id=target_run,
        session_date=manifest.session_date,
        archive_filename=manifest.archive_filename,
        table_counts=counts,
    )


def maintain_research_archives(
    *,
    db_path: str | Path | None = None,
    archive_dir: str | Path | None = None,
    keep_hot_runs: int | None = None,
    max_sessions: int = 1,
    progress: Callable[[str], None] | None = None,
) -> ArchiveMaintenanceResult:
    if max_sessions < 1:
        raise ValueError(
            "max_sessions must be >= 1."
        )

    directory = resolve_archive_dir(
        archive_dir
    )
    keep = (
        keep_hot_completed_runs()
        if keep_hot_runs is None
        else int(keep_hot_runs)
    )

    plan = plan_archive_sessions(
        db_path=db_path,
        archive_dir=directory,
        keep_hot_runs=keep,
    )
    eligible = [
        item
        for item in plan
        if item.eligible
    ]

    archived: list[str] = []
    skipped: list[str] = []

    for candidate in eligible:
        if len(archived) >= max_sessions:
            skipped.append(
                candidate.session_date
            )
            continue

        create_research_archive(
            candidate.session_date,
            db_path=db_path,
            archive_dir=directory,
            keep_hot_runs=keep,
            progress=progress,
        )
        archived.append(
            candidate.session_date
        )

    return ArchiveMaintenanceResult(
        archived_count=len(archived),
        archived_sessions=tuple(archived),
        skipped_sessions=tuple(skipped),
    )
