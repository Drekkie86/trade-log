from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, Iterable

from src.database.repository import (
    EXPECTED_SCHEMA_VERSION,
    resolve_db_path,
)
from src.operations.remote_archive import (
    RemoteArchiveProof,
    load_remote_archive_proof,
    verify_remote_archive_proof,
)
from src.operations.research_archive import (
    ResearchArchiveManifest,
    inventory_research_archives,
    keep_hot_completed_runs,
    resolve_archive_dir,
    verify_research_archive,
)


PRUNE_FORMAT_VERSION = 1
PRUNE_GATE_STATE = "OFFHOST_IMMUTABLE_RESTORE_VERIFIED"
PRUNE_RECEIPT_STATE = "REFERENCE_AWARE_HOT_PRUNE_COMMITTED"
DEFAULT_PRUNE_DELETE_BATCH_ROWS = 25_000

PRUNE_PARENT_TABLES = (
    "listing_reference_contracts",
    "option_quotes",
)

TARGET_TABLES = (
    "local_surface_residual_v2_observations",
    "hypothesis_scanner_evaluations",
    "provider_model_observations",
    "provider_observation_availability",
    "listing_reference_contracts",
    "option_quotes",
)

DELETE_TRIGGER_BY_TABLE = {
    "local_surface_residual_v2_observations":
        "trg_local_surface_v2_observation_no_delete",
    "hypothesis_scanner_evaluations":
        "trg_hypothesis_scanner_evaluations_no_delete",
    "provider_model_observations":
        "trg_provider_model_no_delete",
    "provider_observation_availability":
        "trg_provider_observation_no_delete",
    "listing_reference_contracts":
        "trg_listing_reference_no_delete",
    "option_quotes":
        "trg_option_quotes_no_delete",
}

DELETE_ORDER = (
    "local_surface_residual_v2_observations",
    "hypothesis_scanner_evaluations",
    "provider_model_observations",
    "provider_observation_availability",
    "listing_reference_contracts",
    "option_quotes",
)


@dataclass(frozen=True)
class PruneForeignKeyIndexCheck:
    child_table: str
    parent_table: str
    child_columns: tuple[str, ...]
    supporting_index: str | None

    @property
    def supported(self) -> bool:
        return self.supporting_index is not None

    def as_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["child_columns"] = list(
            self.child_columns
        )
        data["supported"] = self.supported
        return data


@dataclass(frozen=True)
class PruneTablePlan:
    table_name: str
    archived_rows: int
    deletable_rows: int
    preserved_rows: int
    archive_count_matches_hot: bool

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class PruneSessionPlan:
    session_date: str
    run_ids: tuple[int, ...]
    min_run_id: int
    max_run_id: int
    current_schema_version: int
    expected_schema_version: int
    hot_floor_run_id: int | None
    outside_hot_window: bool
    archive_manifest_filename: str
    remote_proof_filename: str
    remote_gate_state: str
    local_archive_fast_verified: bool
    run_lineage_verified: bool
    foreign_key_indexes_verified: bool
    foreign_key_index_checks: tuple[
        PruneForeignKeyIndexCheck,
        ...,
    ]
    tables: tuple[PruneTablePlan, ...]
    total_archived_rows: int
    total_deletable_rows: int
    total_preserved_rows: int
    apply_eligible: bool
    blockers: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            **asdict(self),
            "run_ids": list(self.run_ids),
            "foreign_key_index_checks": [
                item.as_dict()
                for item
                in self.foreign_key_index_checks
            ],
            "tables": [
                item.as_dict()
                for item in self.tables
            ],
            "blockers": list(self.blockers),
        }


@dataclass(frozen=True)
class PruneReceipt:
    format_version: int
    state: str
    committed_at: str
    session_date: str
    run_ids: tuple[int, ...]
    archive_manifest_filename: str
    archive_manifest_sha256: str
    remote_proof_filename: str
    remote_proof_sha256: str
    remote_gate_state: str
    schema_version: int
    trigger_sql_sha256_before: dict[str, str]
    trigger_sql_sha256_after: dict[str, str]
    rows_before: dict[str, int]
    rows_deleted: dict[str, int]
    rows_preserved: dict[str, int]
    freelist_bytes_before: int
    freelist_bytes_after: int
    database_size_bytes_before: int
    database_size_bytes_after: int
    foreign_key_check: str

    def as_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["run_ids"] = list(self.run_ids)
        return data


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _normalized_sql_sha256(sql: str) -> str:
    normalized = " ".join(
        sql.split()
    ).strip()
    return _sha256_bytes(
        normalized.encode("utf-8")
    )


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

        if os.name != "nt":
            flags = os.O_RDONLY | getattr(
                os,
                "O_DIRECTORY",
                0,
            )
            fd = os.open(path.parent, flags)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
    finally:
        if temp.exists():
            temp.unlink()


def _manifest_for_session(
    session_date: str,
    archive_dir: Path,
) -> tuple[Path, ResearchArchiveManifest]:
    inventory = inventory_research_archives(
        archive_dir
    )
    matches = [
        manifest
        for manifest in inventory.manifests
        if manifest.session_date == session_date
    ]
    if not matches:
        raise FileNotFoundError(
            "No verified local research archive exists "
            f"for session {session_date}."
        )
    if len(matches) != 1:
        raise RuntimeError(
            "Expected exactly one local research archive "
            f"for session {session_date}; found {len(matches)}."
        )

    manifest = matches[0]
    path = (
        archive_dir
        / manifest.manifest_filename
    )
    return path, manifest


def _proof_path_for_manifest(
    manifest_path: Path,
) -> Path:
    suffix = ".manifest.json"
    if not manifest_path.name.endswith(suffix):
        raise ValueError(
            "Unexpected archive manifest filename."
        )
    return manifest_path.with_name(
        manifest_path.name[
            :-len(suffix)
        ]
        + ".remote-proof.json"
    )


def _validate_local_proof_binding(
    *,
    manifest_path: Path,
    manifest: ResearchArchiveManifest,
    proof_path: Path,
    proof: RemoteArchiveProof,
) -> None:
    if proof.pruning_gate_state != PRUNE_GATE_STATE:
        raise RuntimeError(
            "Remote proof does not satisfy Christiania's "
            f"pruning gate: {proof.pruning_gate_state}"
        )
    if proof.session_date != manifest.session_date:
        raise RuntimeError(
            "Remote proof session does not match archive manifest."
        )
    if (
        proof.local_manifest_filename
        != manifest.manifest_filename
    ):
        raise RuntimeError(
            "Remote proof manifest filename does not match "
            "the local archive manifest."
        )
    if (
        proof.local_archive_filename
        != manifest.archive_filename
    ):
        raise RuntimeError(
            "Remote proof archive filename does not match "
            "the local archive manifest."
        )
    if (
        proof.local_archive_compressed_sha256
        != manifest.compressed_sha256
    ):
        raise RuntimeError(
            "Remote proof compressed hash does not match "
            "the local archive manifest."
        )
    if (
        proof.local_archive_uncompressed_sha256
        != manifest.uncompressed_sha256
    ):
        raise RuntimeError(
            "Remote proof payload hash does not match "
            "the local archive manifest."
        )
    manifest_hash = _sha256_file(
        manifest_path
    )
    if (
        proof.local_manifest_sha256
        != manifest_hash
    ):
        raise RuntimeError(
            "Remote proof does not bind to the current "
            "local archive manifest bytes."
        )
    if not proof_path.is_file():
        raise FileNotFoundError(
            f"Remote proof missing: {proof_path}"
        )


def _sqlite_version(
    conn: sqlite3.Connection,
) -> int:
    row = conn.execute(
        """
        SELECT MAX(version)
        FROM schema_version;
        """
    ).fetchone()
    if row is None or row[0] is None:
        raise RuntimeError(
            "Christiania database has no schema_version."
        )
    return int(row[0])


def _quote_identifier(
    value: str,
) -> str:
    return '"' + value.replace(
        '"',
        '""',
    ) + '"'


def _foreign_key_index_checks(
    conn: sqlite3.Connection,
) -> tuple[PruneForeignKeyIndexCheck, ...]:
    checks: list[
        PruneForeignKeyIndexCheck
    ] = []

    child_tables = [
        str(row[0])
        for row in conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name NOT LIKE 'sqlite_%'
            ORDER BY name;
            """
        ).fetchall()
    ]

    for child_table in child_tables:
        quoted_child = _quote_identifier(
            child_table
        )
        fk_rows = conn.execute(
            f"PRAGMA foreign_key_list({quoted_child});"
        ).fetchall()

        grouped: dict[
            int,
            list[tuple],
        ] = {}

        for row in fk_rows:
            parent_table = str(
                row[2]
            )
            if (
                parent_table
                not in PRUNE_PARENT_TABLES
            ):
                continue

            grouped.setdefault(
                int(row[0]),
                [],
            ).append(row)

        if not grouped:
            continue

        index_rows = conn.execute(
            f"PRAGMA index_list({quoted_child});"
        ).fetchall()

        usable_indexes: list[
            tuple[str, tuple[str, ...]]
        ] = []

        for index_row in index_rows:
            index_name = str(
                index_row[1]
            )

            # Partial indexes cannot cover every possible FK child row.
            partial = (
                int(index_row[4])
                if len(index_row) > 4
                else 0
            )
            if partial:
                continue

            quoted_index = (
                _quote_identifier(
                    index_name
                )
            )
            column_rows = conn.execute(
                f"PRAGMA index_info({quoted_index});"
            ).fetchall()

            columns = tuple(
                str(row[2])
                for row in sorted(
                    column_rows,
                    key=lambda item: int(
                        item[0]
                    ),
                )
                if row[2] is not None
            )

            if columns:
                usable_indexes.append(
                    (
                        index_name,
                        columns,
                    )
                )

        for rows in grouped.values():
            ordered = sorted(
                rows,
                key=lambda item: int(
                    item[1]
                ),
            )

            parent_table = str(
                ordered[0][2]
            )
            child_columns = tuple(
                str(row[3])
                for row in ordered
            )

            support = next(
                (
                    index_name
                    for (
                        index_name,
                        columns,
                    )
                    in usable_indexes
                    if columns[
                        :len(
                            child_columns
                        )
                    ]
                    == child_columns
                ),
                None,
            )

            checks.append(
                PruneForeignKeyIndexCheck(
                    child_table=child_table,
                    parent_table=parent_table,
                    child_columns=
                        child_columns,
                    supporting_index=support,
                )
            )

    return tuple(
        sorted(
            checks,
            key=lambda item: (
                item.parent_table,
                item.child_table,
                item.child_columns,
            ),
        )
    )


def _page_freelist_bytes(
    conn: sqlite3.Connection,
) -> int:
    page_size = int(
        conn.execute(
            "PRAGMA page_size;"
        ).fetchone()[0]
    )
    freelist = int(
        conn.execute(
            "PRAGMA freelist_count;"
        ).fetchone()[0]
    )
    return page_size * freelist


def _prepare_run_scope(
    conn: sqlite3.Connection,
    run_ids: Iterable[int],
) -> None:
    conn.execute(
        """
        CREATE TEMP TABLE IF NOT EXISTS _prune_runs(
            id INTEGER PRIMARY KEY
        );
        """
    )
    conn.execute(
        "DELETE FROM _prune_runs;"
    )
    conn.executemany(
        """
        INSERT INTO _prune_runs(id)
        VALUES(?);
        """,
        (
            (int(run_id),)
            for run_id in run_ids
        ),
    )


def _emit_progress(
    progress: Callable[[str], None] | None,
    message: str,
) -> None:
    if progress is not None:
        progress(message)


def _execute_with_progress(
    conn: sqlite3.Connection,
    *,
    label: str,
    sql: str,
    progress: Callable[[str], None] | None,
) -> int:
    started = time.monotonic()
    next_heartbeat = started + 10.0

    _emit_progress(
        progress,
        f"planner: {label} started",
    )

    def heartbeat() -> int:
        nonlocal next_heartbeat

        now = time.monotonic()
        if (
            progress is not None
            and now >= next_heartbeat
        ):
            progress(
                f"planner: {label} still running "
                f"elapsed={now - started:.1f}s"
            )
            next_heartbeat = now + 10.0

        return 0

    conn.set_progress_handler(
        heartbeat,
        250_000,
    )
    try:
        conn.execute(sql)
        changed = int(
            conn.execute(
                "SELECT changes();"
            ).fetchone()[0]
        )
    finally:
        conn.set_progress_handler(
            None,
            0,
        )

    elapsed = (
        time.monotonic()
        - started
    )
    _emit_progress(
        progress,
        f"planner: {label} complete "
        f"rows={changed} elapsed={elapsed:.1f}s",
    )
    return changed


_SCOPE_TABLE_BY_TARGET = {
    "local_surface_residual_v2_observations":
        "_scope_surface_obs",
    "hypothesis_scanner_evaluations":
        "_scope_scanner_evals",
    "provider_model_observations":
        "_scope_provider_models",
    "provider_observation_availability":
        "_scope_provider_availability",
    "listing_reference_contracts":
        "_scope_listing_refs",
    "option_quotes":
        "_scope_option_quotes",
}


_DELETE_TABLE_BY_TARGET = {
    "local_surface_residual_v2_observations":
        "_delete_surface_obs",
    "hypothesis_scanner_evaluations":
        "_delete_scanner_evals",
    "provider_model_observations":
        "_delete_provider_models",
    "provider_observation_availability":
        "_delete_provider_availability",
    "listing_reference_contracts":
        "_delete_listing_refs",
    "option_quotes":
        "_delete_option_quotes",
}


def _prepare_delete_sets(
    conn: sqlite3.Connection,
    *,
    progress: Callable[[str], None] | None = None,
) -> tuple[
    dict[str, int],
    dict[str, int],
]:
    # The first V2C production planner used correlated NOT EXISTS queries
    # directly against the full hot database. Those predicates were safe but
    # could become effectively quadratic where downstream FK columns lacked
    # dedicated indexes. Materialize the one-session population once, then
    # scan each downstream evidence family once into indexed temp keep-sets.
    for name in (
        *_SCOPE_TABLE_BY_TARGET.values(),
        *_DELETE_TABLE_BY_TARGET.values(),
        "_keep_surface_obs",
        "_keep_scanner_evals",
        "_keep_provider_models",
        "_keep_provider_availability",
        "_keep_listing_refs",
        "_keep_option_quotes",
    ):
        conn.execute(
            f"""
            CREATE TEMP TABLE IF NOT EXISTS {name}(
                id INTEGER PRIMARY KEY
            ) WITHOUT ROWID;
            """
        )
        conn.execute(
            f"DELETE FROM {name};"
        )

    candidates: dict[str, int] = {}

    candidates[
        "listing_reference_contracts"
    ] = _execute_with_progress(
        conn,
        label="scope listing_reference_contracts",
        sql="""
            INSERT INTO _scope_listing_refs(id)
            SELECT lrc.id
            FROM listing_reference_contracts AS lrc
            JOIN _prune_runs AS pr
              ON pr.id = lrc.research_run_id;
        """,
        progress=progress,
    )

    candidates[
        "option_quotes"
    ] = _execute_with_progress(
        conn,
        label="scope option_quotes",
        sql="""
            INSERT INTO _scope_option_quotes(id)
            SELECT oq.id
            FROM market_snapshots AS ms
            JOIN _prune_runs AS pr
              ON pr.id = ms.research_run_id
            JOIN option_quotes AS oq
              ON oq.snapshot_id = ms.id;
        """,
        progress=progress,
    )

    scope_sql = (
        (
            "local_surface_residual_v2_observations",
            """
            INSERT INTO _scope_surface_obs(id)
            SELECT o.id
            FROM local_surface_residual_v2_runs AS r
            JOIN _prune_runs AS pr
              ON pr.id = r.research_run_id
            JOIN local_surface_residual_v2_observations AS o
              ON o.model_run_id = r.id;
            """,
        ),
        (
            "hypothesis_scanner_evaluations",
            """
            INSERT INTO _scope_scanner_evals(id)
            SELECT e.id
            FROM hypothesis_scanner_runs AS r
            JOIN _prune_runs AS pr
              ON pr.id = r.research_run_id
            JOIN hypothesis_scanner_evaluations AS e
              ON e.scanner_run_id = r.id;
            """,
        ),
        (
            "provider_model_observations",
            """
            INSERT INTO _scope_provider_models(id)
            SELECT pmo.id
            FROM _scope_option_quotes AS s
            JOIN provider_model_observations AS pmo
              ON pmo.option_quote_id = s.id;
            """,
        ),
        (
            "provider_observation_availability",
            """
            INSERT INTO _scope_provider_availability(id)
            SELECT poa.id
            FROM _scope_listing_refs AS s
            JOIN provider_observation_availability AS poa
              ON poa.reference_contract_id = s.id;
            """,
        ),
    )

    for (
        table_name,
        sql,
    ) in scope_sql:
        candidates[
            table_name
        ] = _execute_with_progress(
            conn,
            label=(
                "scope "
                + table_name
            ),
            sql=sql,
            progress=progress,
        )

    # Each keep-set scans the downstream family once and probes the
    # session-scoped PRIMARY KEY temp table. This avoids one downstream scan
    # per archived parent row.
    _execute_with_progress(
        conn,
        label="references Surface V2 -> empirical null",
        sql="""
            INSERT OR IGNORE INTO _keep_surface_obs(id)
            SELECT m.v2_observation_id
            FROM local_surface_null_v1_membership AS m
            JOIN _scope_surface_obs AS s
              ON s.id = m.v2_observation_id;
        """,
        progress=progress,
    )

    _execute_with_progress(
        conn,
        label="references scanner -> shadow proposals",
        sql="""
            INSERT OR IGNORE INTO _keep_scanner_evals(id)
            SELECT p.hypothesis_evaluation_id
            FROM shadow_structure_proposals AS p
            JOIN _scope_scanner_evals AS s
              ON s.id = p.hypothesis_evaluation_id;
        """,
        progress=progress,
    )

    _execute_with_progress(
        conn,
        label="references provider models -> timing reconstruction",
        sql="""
            INSERT OR IGNORE INTO _keep_provider_models(id)
            SELECT tr.provider_model_observation_id
            FROM provider_model_timing_reconstruction_v1 AS tr
            JOIN _scope_provider_models AS s
              ON s.id = tr.provider_model_observation_id;
        """,
        progress=progress,
    )

    _execute_with_progress(
        conn,
        label="references provider availability -> shadow candidates",
        sql="""
            INSERT OR IGNORE INTO _keep_provider_availability(id)
            SELECT sc.entry_quote_observation_id
            FROM shadow_candidates AS sc
            JOIN _scope_provider_availability AS s
              ON s.id = sc.entry_quote_observation_id
            WHERE sc.entry_quote_observation_id IS NOT NULL

            UNION

            SELECT sc.entry_greek_observation_id
            FROM shadow_candidates AS sc
            JOIN _scope_provider_availability AS s
              ON s.id = sc.entry_greek_observation_id
            WHERE sc.entry_greek_observation_id IS NOT NULL;
        """,
        progress=progress,
    )

    _execute_with_progress(
        conn,
        label="delete-set Surface V2",
        sql="""
            INSERT INTO _delete_surface_obs(id)
            SELECT s.id
            FROM _scope_surface_obs AS s
            LEFT JOIN _keep_surface_obs AS k
              ON k.id = s.id
            WHERE k.id IS NULL;
        """,
        progress=progress,
    )

    _execute_with_progress(
        conn,
        label="delete-set scanner evaluations",
        sql="""
            INSERT INTO _delete_scanner_evals(id)
            SELECT s.id
            FROM _scope_scanner_evals AS s
            LEFT JOIN _keep_scanner_evals AS k
              ON k.id = s.id
            WHERE k.id IS NULL;
        """,
        progress=progress,
    )

    _execute_with_progress(
        conn,
        label="delete-set provider models",
        sql="""
            INSERT INTO _delete_provider_models(id)
            SELECT s.id
            FROM _scope_provider_models AS s
            LEFT JOIN _keep_provider_models AS k
              ON k.id = s.id
            WHERE k.id IS NULL;
        """,
        progress=progress,
    )

    _execute_with_progress(
        conn,
        label="delete-set provider availability",
        sql="""
            INSERT INTO _delete_provider_availability(id)
            SELECT s.id
            FROM _scope_provider_availability AS s
            LEFT JOIN _keep_provider_availability AS k
              ON k.id = s.id
            WHERE k.id IS NULL;
        """,
        progress=progress,
    )

    # Listing-reference keep-set: direct downstream consumers plus any
    # session-scoped child that survived its own reference check.
    _execute_with_progress(
        conn,
        label="references listing refs -> surviving consumers",
        sql="""
            INSERT OR IGNORE INTO _keep_listing_refs(id)
            SELECT sc.reference_contract_id
            FROM shadow_candidates AS sc
            JOIN _scope_listing_refs AS s
              ON s.id = sc.reference_contract_id

            UNION

            SELECT sp.target_reference_contract_id
            FROM shadow_structure_proposals AS sp
            JOIN _scope_listing_refs AS s
              ON s.id = sp.target_reference_contract_id

            UNION

            SELECT poa.reference_contract_id
            FROM provider_observation_availability AS poa
            JOIN _scope_provider_availability AS s
              ON s.id = poa.id
            LEFT JOIN _delete_provider_availability AS d
              ON d.id = poa.id
            WHERE d.id IS NULL

            UNION

            SELECT e.reference_contract_id
            FROM hypothesis_scanner_evaluations AS e
            JOIN _scope_scanner_evals AS s
              ON s.id = e.id
            LEFT JOIN _delete_scanner_evals AS d
              ON d.id = e.id
            WHERE d.id IS NULL

            UNION

            SELECT o.reference_contract_id
            FROM local_surface_residual_v2_observations AS o
            JOIN _scope_surface_obs AS s
              ON s.id = o.id
            LEFT JOIN _delete_surface_obs AS d
              ON d.id = o.id
            WHERE d.id IS NULL;
        """,
        progress=progress,
    )

    _execute_with_progress(
        conn,
        label="delete-set listing references",
        sql="""
            INSERT INTO _delete_listing_refs(id)
            SELECT s.id
            FROM _scope_listing_refs AS s
            LEFT JOIN _keep_listing_refs AS k
              ON k.id = s.id
            WHERE k.id IS NULL;
        """,
        progress=progress,
    )

    # Quote keep-set: direct downstream consumers plus any scoped child that
    # survived its own reference check.
    _execute_with_progress(
        conn,
        label="references quotes -> surviving consumers",
        sql="""
            INSERT OR IGNORE INTO _keep_option_quotes(id)
            SELECT cl.option_quote_id
            FROM candidate_legs AS cl
            JOIN _scope_option_quotes AS s
              ON s.id = cl.option_quote_id

            UNION

            SELECT cc.control_quote_id
            FROM candidate_controls AS cc
            JOIN _scope_option_quotes AS s
              ON s.id = cc.control_quote_id

            UNION

            SELECT rs.option_quote_id
            FROM research_selections AS rs
            JOIN _scope_option_quotes AS s
              ON s.id = rs.option_quote_id

            UNION

            SELECT se.option_quote_id
            FROM selection_exclusions AS se
            JOIN _scope_option_quotes AS s
              ON s.id = se.option_quote_id

            UNION

            SELECT so.option_quote_id
            FROM saxo_option_observations AS so
            JOIN _scope_option_quotes AS s
              ON s.id = so.option_quote_id

            UNION

            SELECT sf.option_quote_id
            FROM saxo_resolution_failures AS sf
            JOIN _scope_option_quotes AS s
              ON s.id = sf.option_quote_id

            UNION

            SELECT pmo.option_quote_id
            FROM provider_model_observations AS pmo
            JOIN _scope_provider_models AS s
              ON s.id = pmo.id
            LEFT JOIN _delete_provider_models AS d
              ON d.id = pmo.id
            WHERE d.id IS NULL

            UNION

            SELECT e.option_quote_id
            FROM hypothesis_scanner_evaluations AS e
            JOIN _scope_scanner_evals AS s
              ON s.id = e.id
            LEFT JOIN _delete_scanner_evals AS d
              ON d.id = e.id
            WHERE d.id IS NULL

            UNION

            SELECT o.option_quote_id
            FROM local_surface_residual_v2_observations AS o
            JOIN _scope_surface_obs AS s
              ON s.id = o.id
            LEFT JOIN _delete_surface_obs AS d
              ON d.id = o.id
            WHERE d.id IS NULL;
        """,
        progress=progress,
    )

    _execute_with_progress(
        conn,
        label="delete-set option quotes",
        sql="""
            INSERT INTO _delete_option_quotes(id)
            SELECT s.id
            FROM _scope_option_quotes AS s
            LEFT JOIN _keep_option_quotes AS k
              ON k.id = s.id
            WHERE k.id IS NULL;
        """,
        progress=progress,
    )

    deletable = {
        table_name: int(
            conn.execute(
                f"""
                SELECT COUNT(*)
                FROM {
                    _DELETE_TABLE_BY_TARGET[
                        table_name
                    ]
                };
                """
            ).fetchone()[0]
        )
        for table_name
        in TARGET_TABLES
    }

    return (
        candidates,
        deletable,
    )

def _candidate_counts(
    conn: sqlite3.Connection,
) -> dict[str, int]:
    # After delete-set preparation, the scoped temp tables are the cheapest
    # authoritative way to reconcile the live rows for this session.
    return {
        table_name: int(
            conn.execute(
                f"""
                SELECT COUNT(*)
                FROM {
                    _SCOPE_TABLE_BY_TARGET[
                        table_name
                    ]
                } AS s
                JOIN {table_name} AS t
                  ON t.id = s.id;
                """
            ).fetchone()[0]
        )
        for table_name
        in TARGET_TABLES
    }


def _hot_floor_run_id(
    conn: sqlite3.Connection,
) -> int | None:
    keep = keep_hot_completed_runs()
    rows = conn.execute(
        """
        SELECT id
        FROM research_runs
        WHERE status = 'COMPLETED'
        ORDER BY id DESC
        LIMIT ?;
        """,
        (keep,),
    ).fetchall()
    if len(rows) < keep:
        return None
    return min(
        int(row[0])
        for row in rows
    )


def _validate_run_lineage(
    conn: sqlite3.Connection,
    *,
    manifest: ResearchArchiveManifest,
) -> bool:
    rows = conn.execute(
        """
        SELECT
            rr.id,
            rr.us_session_date,
            rr.status
        FROM research_runs AS rr
        JOIN _prune_runs AS pr
          ON pr.id = rr.id
        ORDER BY rr.id;
        """
    ).fetchall()

    if tuple(
        int(row[0])
        for row in rows
    ) != manifest.run_ids:
        return False

    for row in rows:
        if str(row[1]) != manifest.session_date:
            return False
        if str(row[2]) not in {
            "COMPLETED",
            "FAILED",
            "INVALID",
        }:
            return False

    return True


def _build_plan_from_connection(
    conn: sqlite3.Connection,
    *,
    database: Path,
    manifest_path: Path,
    manifest: ResearchArchiveManifest,
    proof_path: Path,
    proof: RemoteArchiveProof,
    local_archive_fast_verified: bool,
    progress: Callable[[str], None] | None = None,
) -> PruneSessionPlan:
    schema_version = _sqlite_version(
        conn
    )
    _prepare_run_scope(
        conn,
        manifest.run_ids,
    )
    lineage_ok = _validate_run_lineage(
        conn,
        manifest=manifest,
    )
    foreign_key_index_checks = (
        _foreign_key_index_checks(
            conn
        )
    )
    foreign_key_indexes_ok = all(
        check.supported
        for check
        in foreign_key_index_checks
    )

    (
        candidates,
        deletable,
    ) = _prepare_delete_sets(
        conn,
        progress=progress,
    )

    table_plans: list[
        PruneTablePlan
    ] = []
    blockers: list[str] = []

    for table_name in TARGET_TABLES:
        archived_rows = candidates[
            table_name
        ]
        expected = int(
            manifest.table_counts.get(
                table_name,
                -1,
            )
        )
        archive_matches = (
            expected == archived_rows
        )
        if not archive_matches:
            blockers.append(
                "ARCHIVE_COUNT_MISMATCH:"
                f"{table_name}:"
                f"hot={archived_rows}:"
                f"archive={expected}"
            )

        delete_count = deletable[
            table_name
        ]
        if (
            delete_count < 0
            or delete_count > archived_rows
        ):
            blockers.append(
                "INVALID_DELETE_COUNT:"
                f"{table_name}"
            )

        table_plans.append(
            PruneTablePlan(
                table_name=table_name,
                archived_rows=archived_rows,
                deletable_rows=delete_count,
                preserved_rows=(
                    archived_rows
                    - delete_count
                ),
                archive_count_matches_hot=
                    archive_matches,
            )
        )

    hot_floor = _hot_floor_run_id(conn)
    outside_hot = (
        hot_floor is not None
        and manifest.max_run_id < hot_floor
    )

    if not foreign_key_indexes_ok:
        for check in foreign_key_index_checks:
            if check.supported:
                continue
            blockers.append(
                "MISSING_PRUNE_PARENT_FK_INDEX:"
                f"{check.child_table}:"
                + ",".join(
                    check.child_columns
                )
                + f"->{check.parent_table}"
            )

    if schema_version != EXPECTED_SCHEMA_VERSION:
        blockers.append(
            "SCHEMA_MISMATCH:"
            f"{schema_version}!="
            f"{EXPECTED_SCHEMA_VERSION}"
        )
    if not lineage_ok:
        blockers.append(
            "RUN_LINEAGE_MISMATCH"
        )
    if not outside_hot:
        blockers.append(
            "SESSION_NOT_OUTSIDE_HOT_WINDOW"
        )
    if (
        proof.pruning_gate_state
        != PRUNE_GATE_STATE
    ):
        blockers.append(
            "REMOTE_GATE_NOT_VERIFIED"
        )
    if not local_archive_fast_verified:
        blockers.append(
            "LOCAL_ARCHIVE_NOT_VERIFIED"
        )

    total_archived = sum(
        item.archived_rows
        for item in table_plans
    )
    total_deletable = sum(
        item.deletable_rows
        for item in table_plans
    )
    total_preserved = sum(
        item.preserved_rows
        for item in table_plans
    )

    if total_deletable <= 0:
        blockers.append(
            "NO_REFERENCE_SAFE_ROWS_TO_PRUNE"
        )

    return PruneSessionPlan(
        session_date=manifest.session_date,
        run_ids=manifest.run_ids,
        min_run_id=manifest.min_run_id,
        max_run_id=manifest.max_run_id,
        current_schema_version=schema_version,
        expected_schema_version=
            EXPECTED_SCHEMA_VERSION,
        hot_floor_run_id=hot_floor,
        outside_hot_window=outside_hot,
        archive_manifest_filename=
            manifest.manifest_filename,
        remote_proof_filename=
            proof_path.name,
        remote_gate_state=
            proof.pruning_gate_state,
        local_archive_fast_verified=
            local_archive_fast_verified,
        run_lineage_verified=lineage_ok,
        foreign_key_indexes_verified=
            foreign_key_indexes_ok,
        foreign_key_index_checks=
            foreign_key_index_checks,
        tables=tuple(table_plans),
        total_archived_rows=total_archived,
        total_deletable_rows=
            total_deletable,
        total_preserved_rows=
            total_preserved,
        apply_eligible=not blockers,
        blockers=tuple(blockers),
    )


def plan_prune_session(
    session_date: str,
    *,
    db_path: str | Path | None = None,
    archive_dir: str | Path | None = None,
    verify_remote: bool = False,
    progress: Callable[[str], None] | None = None,
) -> PruneSessionPlan:
    database = resolve_db_path(
        db_path
    )
    directory = resolve_archive_dir(
        archive_dir
    )

    (
        manifest_path,
        manifest,
    ) = _manifest_for_session(
        session_date,
        directory,
    )
    proof_path = _proof_path_for_manifest(
        manifest_path
    )
    if not proof_path.is_file():
        raise FileNotFoundError(
            "No off-host immutable proof exists for "
            f"session {session_date}."
        )

    local_archive = verify_research_archive(
        manifest_path,
        deep_payload=False,
    )
    local_verified = (
        local_archive.compressed_sha256
        == manifest.compressed_sha256
    )

    proof = load_remote_archive_proof(
        proof_path
    )
    _validate_local_proof_binding(
        manifest_path=manifest_path,
        manifest=manifest,
        proof_path=proof_path,
        proof=proof,
    )

    if verify_remote:
        _emit_progress(
            progress,
            "planner: remote immutable proof revalidation started",
        )
        proof = verify_remote_archive_proof(
            proof_path,
            progress=progress,
        )
        _emit_progress(
            progress,
            "planner: remote immutable proof revalidation complete",
        )

    uri = (
        database.resolve().as_uri()
        + "?mode=ro"
    )
    conn = sqlite3.connect(
        uri,
        uri=True,
        timeout=60.0,
    )
    conn.execute(
        "PRAGMA temp_store = FILE;"
    )
    try:
        return _build_plan_from_connection(
            conn,
            database=database,
            manifest_path=manifest_path,
            manifest=manifest,
            proof_path=proof_path,
            proof=proof,
            local_archive_fast_verified=
                local_verified,
            progress=progress,
        )
    finally:
        conn.close()


def _capture_delete_triggers(
    conn: sqlite3.Connection,
) -> dict[str, str]:
    captured: dict[str, str] = {}

    for (
        table_name,
        trigger_name,
    ) in DELETE_TRIGGER_BY_TABLE.items():
        row = conn.execute(
            """
            SELECT
                tbl_name,
                sql
            FROM sqlite_master
            WHERE type = 'trigger'
              AND name = ?;
            """,
            (trigger_name,),
        ).fetchone()

        if row is None:
            raise RuntimeError(
                "Required immutability trigger is missing: "
                f"{trigger_name}"
            )

        if str(row[0]) != table_name:
            raise RuntimeError(
                "Immutability trigger is attached to an "
                "unexpected table: "
                f"{trigger_name}:{row[0]}"
            )

        sql = str(
            row[1] or ""
        )
        if (
            "BEFORE DELETE"
            not in " ".join(
                sql.upper().split()
            )
        ):
            raise RuntimeError(
                "Expected a BEFORE DELETE immutability trigger: "
                f"{trigger_name}"
            )

        captured[
            trigger_name
        ] = sql

    return captured


def _trigger_hashes(
    trigger_sql: dict[str, str],
) -> dict[str, str]:
    return {
        name: _normalized_sql_sha256(
            sql
        )
        for name, sql
        in trigger_sql.items()
    }


def _drop_delete_triggers(
    conn: sqlite3.Connection,
    trigger_sql: dict[str, str],
) -> None:
    for trigger_name in trigger_sql:
        if not trigger_name.replace(
            "_",
            "",
        ).isalnum():
            raise RuntimeError(
                "Unsafe trigger name."
            )
        conn.execute(
            f'DROP TRIGGER "{trigger_name}";'
        )


def _restore_delete_triggers(
    conn: sqlite3.Connection,
    trigger_sql: dict[str, str],
) -> dict[str, str]:
    for sql in trigger_sql.values():
        conn.execute(sql)

    restored = _capture_delete_triggers(
        conn
    )
    return restored


def _delete_reference_safe_rows(
    conn: sqlite3.Connection,
    *,
    progress: Callable[[str], None] | None = None,
    batch_rows: int = DEFAULT_PRUNE_DELETE_BATCH_ROWS,
) -> dict[str, int]:
    if batch_rows < 1:
        raise ValueError(
            "batch_rows must be >= 1."
        )

    temp_by_table = {
        "local_surface_residual_v2_observations":
            "_delete_surface_obs",
        "hypothesis_scanner_evaluations":
            "_delete_scanner_evals",
        "provider_model_observations":
            "_delete_provider_models",
        "provider_observation_availability":
            "_delete_provider_availability",
        "listing_reference_contracts":
            "_delete_listing_refs",
        "option_quotes":
            "_delete_option_quotes",
    }

    deleted: dict[str, int] = {}

    for table_name in DELETE_ORDER:
        temp_table = temp_by_table[
            table_name
        ]

        expected = int(
            conn.execute(
                f"""
                SELECT COUNT(*)
                FROM {temp_table};
                """
            ).fetchone()[0]
        )

        total = 0
        last_id: int | None = None
        batch_number = 0
        started = time.monotonic()

        _emit_progress(
            progress,
            "prune-delete: "
            f"{table_name} started "
            f"rows={expected} "
            f"batch_rows={batch_rows}",
        )

        while total < expected:
            if last_id is None:
                batch_ids = conn.execute(
                    f"""
                    SELECT id
                    FROM {temp_table}
                    ORDER BY id
                    LIMIT ?;
                    """,
                    (batch_rows,),
                ).fetchall()
            else:
                batch_ids = conn.execute(
                    f"""
                    SELECT id
                    FROM {temp_table}
                    WHERE id > ?
                    ORDER BY id
                    LIMIT ?;
                    """,
                    (
                        last_id,
                        batch_rows,
                    ),
                ).fetchall()

            if not batch_ids:
                break

            batch_last_id = int(
                batch_ids[-1][0]
            )

            if last_id is None:
                cursor = conn.execute(
                    f"""
                    DELETE FROM {table_name}
                    WHERE id IN (
                        SELECT id
                        FROM {temp_table}
                        WHERE id <= ?
                    );
                    """,
                    (batch_last_id,),
                )
            else:
                cursor = conn.execute(
                    f"""
                    DELETE FROM {table_name}
                    WHERE id IN (
                        SELECT id
                        FROM {temp_table}
                        WHERE id > ?
                          AND id <= ?
                    );
                    """,
                    (
                        last_id,
                        batch_last_id,
                    ),
                )

            changed = int(
                conn.execute(
                    "SELECT changes();"
                ).fetchone()[0]
            )
            del cursor

            batch_number += 1
            total += changed
            last_id = batch_last_id

            _emit_progress(
                progress,
                "prune-delete: "
                f"{table_name} "
                f"batch={batch_number} "
                f"rows={changed} "
                f"total={total}/{expected} "
                f"elapsed="
                f"{time.monotonic() - started:.1f}s",
            )

            if changed <= 0:
                raise RuntimeError(
                    "Chunked prune delete made no "
                    f"progress for {table_name}."
                )

        if total != expected:
            raise RuntimeError(
                "Chunked prune delete count "
                f"mismatch for {table_name}: "
                f"deleted={total} "
                f"expected={expected}."
            )

        _emit_progress(
            progress,
            "prune-delete: "
            f"{table_name} complete "
            f"rows={total} "
            f"batches={batch_number} "
            f"elapsed="
            f"{time.monotonic() - started:.1f}s",
        )

        deleted[
            table_name
        ] = total

    return deleted


def _foreign_key_violations(
    conn: sqlite3.Connection,
) -> list[tuple]:
    return list(
        conn.execute(
            "PRAGMA foreign_key_check;"
        ).fetchall()
    )


def prune_receipt_path(
    manifest_path: Path,
) -> Path:
    suffix = ".manifest.json"
    stem = manifest_path.name[
        :-len(suffix)
    ]
    return manifest_path.with_name(
        stem
        + ".prune-receipt.json"
    )


def prune_research_session(
    session_date: str,
    *,
    db_path: str | Path | None = None,
    archive_dir: str | Path | None = None,
    confirm_session: str,
    progress: Callable[[str], None] | None = None,
) -> PruneReceipt:
    if confirm_session != session_date:
        raise RuntimeError(
            "Destructive prune confirmation does not match "
            "the requested session."
        )

    database = resolve_db_path(
        db_path
    )
    directory = resolve_archive_dir(
        archive_dir
    )
    (
        manifest_path,
        manifest,
    ) = _manifest_for_session(
        session_date,
        directory,
    )
    proof_path = _proof_path_for_manifest(
        manifest_path
    )

    receipt_path = prune_receipt_path(
        manifest_path
    )
    if receipt_path.exists():
        raise FileExistsError(
            "A prune receipt already exists for this "
            f"session: {receipt_path}"
        )

    # Destructive work is blocked until both independent copies are
    # revalidated immediately before the database transaction.
    _emit_progress(
        progress,
        "prune: deep local archive revalidation started",
    )
    verified_manifest = verify_research_archive(
        manifest_path,
        deep_payload=True,
    )
    _emit_progress(
        progress,
        "prune: deep local archive revalidation complete",
    )
    if (
        verified_manifest.compressed_sha256
        != manifest.compressed_sha256
    ):
        raise RuntimeError(
            "Local archive deep verification does not match "
            "the manifest selected for pruning."
        )

    _emit_progress(
        progress,
        "prune: immutable remote proof revalidation started",
    )
    verified_proof = verify_remote_archive_proof(
        proof_path,
        progress=progress,
    )
    _emit_progress(
        progress,
        "prune: immutable remote proof revalidation complete",
    )
    _validate_local_proof_binding(
        manifest_path=manifest_path,
        manifest=manifest,
        proof_path=proof_path,
        proof=verified_proof,
    )

    db_size_before = (
        database.stat().st_size
    )

    conn = sqlite3.connect(
        database,
        timeout=60.0,
        isolation_level=None,
    )
    try:
        conn.execute(
            "PRAGMA foreign_keys = ON;"
        )
        conn.execute(
            "PRAGMA busy_timeout = 60000;"
        )

        freelist_before = (
            _page_freelist_bytes(
                conn
            )
        )

        conn.execute(
            "PRAGMA temp_store = FILE;"
        )
        _emit_progress(
            progress,
            "prune: acquiring write transaction",
        )
        conn.execute("BEGIN IMMEDIATE;")
        _emit_progress(
            progress,
            "prune: write transaction acquired",
        )
        try:
            plan = _build_plan_from_connection(
                conn,
                database=database,
                manifest_path=manifest_path,
                manifest=manifest,
                proof_path=proof_path,
                proof=verified_proof,
                local_archive_fast_verified=True,
                progress=progress,
            )
            if not plan.apply_eligible:
                raise RuntimeError(
                    "Session is not eligible for reference-aware "
                    "hot pruning: "
                    + "; ".join(
                        plan.blockers
                    )
                )

            trigger_sql = (
                _capture_delete_triggers(
                    conn
                )
            )
            trigger_before = (
                _trigger_hashes(
                    trigger_sql
                )
            )

            rows_before = {
                item.table_name:
                    item.archived_rows
                for item in plan.tables
            }
            expected_delete = {
                item.table_name:
                    item.deletable_rows
                for item in plan.tables
            }

            _emit_progress(
                progress,
                "prune: dropping allow-listed delete guards transactionally",
            )
            _drop_delete_triggers(
                conn,
                trigger_sql,
            )
            deleted = (
                _delete_reference_safe_rows(
                    conn,
                    progress=progress,
                )
            )

            for (
                table_name,
                expected,
            ) in expected_delete.items():
                if deleted[
                    table_name
                ] != expected:
                    raise RuntimeError(
                        "Prune row-count mismatch for "
                        f"{table_name}: "
                        f"deleted={deleted[table_name]} "
                        f"expected={expected}."
                    )

            _emit_progress(
                progress,
                "prune: restoring immutability triggers",
            )
            restored = (
                _restore_delete_triggers(
                    conn,
                    trigger_sql,
                )
            )
            trigger_after = (
                _trigger_hashes(
                    restored
                )
            )
            if (
                trigger_after
                != trigger_before
            ):
                raise RuntimeError(
                    "Immutability triggers were not restored "
                    "byte-semantically after pruning."
                )

            _emit_progress(
                progress,
                "prune: foreign_key_check started",
            )
            violations = (
                _foreign_key_violations(
                    conn
                )
            )
            _emit_progress(
                progress,
                "prune: foreign_key_check complete",
            )
            if violations:
                raise RuntimeError(
                    "Foreign-key violations detected after "
                    "reference-aware pruning: "
                    f"{violations[:10]}"
                )

            remaining = (
                _candidate_counts(
                    conn
                )
            )
            rows_preserved = {
                table_name:
                    int(
                        remaining[
                            table_name
                        ]
                    )
                for table_name
                in TARGET_TABLES
            }

            for table_name in TARGET_TABLES:
                if (
                    rows_before[
                        table_name
                    ]
                    - deleted[
                        table_name
                    ]
                    != rows_preserved[
                        table_name
                    ]
                ):
                    raise RuntimeError(
                        "Post-prune row reconciliation failed "
                        f"for {table_name}."
                    )

            _emit_progress(
                progress,
                "prune: all reconciliation checks passed; committing",
            )
            conn.execute("COMMIT;")
            _emit_progress(
                progress,
                "prune: transaction committed",
            )

        except BaseException:
            # SQLITE_INTERRUPT may already roll back the explicit
            # transaction. Preserve the original failure instead of
            # masking it with "cannot rollback - no transaction is active".
            if conn.in_transaction:
                conn.rollback()
            raise

        freelist_after = (
            _page_freelist_bytes(
                conn
            )
        )

    finally:
        conn.close()

    receipt = PruneReceipt(
        format_version=
            PRUNE_FORMAT_VERSION,
        state=PRUNE_RECEIPT_STATE,
        committed_at=(
            datetime.now(UTC)
            .isoformat()
            .replace("+00:00", "Z")
        ),
        session_date=session_date,
        run_ids=manifest.run_ids,
        archive_manifest_filename=
            manifest.manifest_filename,
        archive_manifest_sha256=
            _sha256_file(
                manifest_path
            ),
        remote_proof_filename=
            proof_path.name,
        remote_proof_sha256=
            _sha256_file(
                proof_path
            ),
        remote_gate_state=
            verified_proof.pruning_gate_state,
        schema_version=
            EXPECTED_SCHEMA_VERSION,
        trigger_sql_sha256_before=
            trigger_before,
        trigger_sql_sha256_after=
            trigger_after,
        rows_before=rows_before,
        rows_deleted=deleted,
        rows_preserved=
            rows_preserved,
        freelist_bytes_before=
            freelist_before,
        freelist_bytes_after=
            freelist_after,
        database_size_bytes_before=
            db_size_before,
        database_size_bytes_after=
            database.stat().st_size,
        foreign_key_check="ok",
    )

    _write_json_atomic(
        receipt_path,
        receipt.as_dict(),
    )
    _emit_progress(
        progress,
        f"prune: receipt written {receipt_path}",
    )
    return receipt
