from __future__ import annotations

import gzip
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Iterator

from src.database.repository import (
    EXPECTED_SCHEMA_VERSION,
    resolve_db_path,
)
from src.operations.research_archive import (
    ARCHIVE_TABLE_SPECS,
    CHUNK_SIZE,
    ResearchArchiveManifest,
    inventory_research_archives,
    resolve_archive_dir,
    verify_research_archive,
)


FINGERPRINT_FETCH_ROWS = 5_000


@dataclass(frozen=True)
class EvidenceTableFingerprint:
    table_name: str
    columns: tuple[str, ...]
    row_count: int
    sha256: str

    def as_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["columns"] = list(
            self.columns
        )
        return data


@dataclass(frozen=True)
class EvidenceTableParity:
    table_name: str
    hot: EvidenceTableFingerprint
    archive: EvidenceTableFingerprint
    matches: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "table_name": self.table_name,
            "hot": self.hot.as_dict(),
            "archive": self.archive.as_dict(),
            "matches": self.matches,
        }


@dataclass(frozen=True)
class ArchiveParityResult:
    session_date: str
    run_ids: tuple[int, ...]
    archive_filename: str
    archive_source_schema_version: int
    hot_schema_version: int
    tables: tuple[
        EvidenceTableParity,
        ...,
    ]

    @property
    def passed(self) -> bool:
        return all(
            item.matches
            for item in self.tables
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "session_date": self.session_date,
            "run_ids": list(
                self.run_ids
            ),
            "archive_filename":
                self.archive_filename,
            "archive_source_schema_version":
                self.archive_source_schema_version,
            "hot_schema_version":
                self.hot_schema_version,
            "passed": self.passed,
            "tables": [
                item.as_dict()
                for item in self.tables
            ],
        }


@dataclass(frozen=True)
class HistoricalSessionProfile:
    session_date: str
    run_ids: tuple[int, ...]
    archive_filename: str
    archive_source_schema_version: int
    table_counts: dict[str, int]
    quote_metrics: dict[str, object]
    provider_model_counts: dict[str, int]
    scanner_state_counts: dict[str, int]
    surface_state_counts: dict[str, int]

    def as_dict(self) -> dict[str, object]:
        return {
            "session_date": self.session_date,
            "run_ids": list(
                self.run_ids
            ),
            "archive_filename":
                self.archive_filename,
            "archive_source_schema_version":
                self.archive_source_schema_version,
            "table_counts":
                dict(self.table_counts),
            "quote_metrics":
                dict(self.quote_metrics),
            "provider_model_counts":
                dict(self.provider_model_counts),
            "scanner_state_counts":
                dict(self.scanner_state_counts),
            "surface_state_counts":
                dict(self.surface_state_counts),
        }


def _emit(
    progress: Callable[[str], None] | None,
    message: str,
) -> None:
    if progress is not None:
        progress(message)


def _manifest_for_session(
    session_date: str,
    *,
    archive_dir: str | Path | None = None,
) -> tuple[
    Path,
    ResearchArchiveManifest,
]:
    directory = resolve_archive_dir(
        archive_dir
    )
    inventory = (
        inventory_research_archives(
            directory
        )
    )

    matches = [
        manifest
        for manifest in inventory.manifests
        if manifest.session_date
        == session_date
    ]

    if not matches:
        raise FileNotFoundError(
            "No verified Christiania research "
            f"archive exists for session "
            f"{session_date}."
        )

    if len(matches) != 1:
        raise RuntimeError(
            "Expected exactly one research archive "
            f"for session {session_date}; "
            f"found {len(matches)}."
        )

    manifest = matches[0]

    return (
        directory
        / manifest.manifest_filename,
        manifest,
    )


@contextmanager
def open_verified_archive_session(
    session_date: str,
    *,
    archive_dir: str | Path | None = None,
    progress: Callable[[str], None] | None = None,
) -> Iterator[
    tuple[
        ResearchArchiveManifest,
        sqlite3.Connection,
    ]
]:
    (
        manifest_path,
        manifest,
    ) = _manifest_for_session(
        session_date,
        archive_dir=archive_dir,
    )

    verified = verify_research_archive(
        manifest_path,
        deep_payload=False,
    )

    if (
        verified.compressed_sha256
        != manifest.compressed_sha256
    ):
        raise RuntimeError(
            "Archive verification changed the "
            "selected manifest identity."
        )

    archive_path = (
        manifest_path.parent
        / manifest.archive_filename
    )

    _emit(
        progress,
        "cold-read: materialization started "
        f"archive={manifest.archive_filename}",
    )

    with tempfile.TemporaryDirectory(
        prefix=(
            "christiania-cold-history-"
        )
    ) as temp_dir:
        restored = (
            Path(temp_dir)
            / "archive.db"
        )

        digest = hashlib.sha256()
        restored_bytes = 0

        with gzip.open(
            archive_path,
            "rb",
        ) as src:
            with restored.open(
                "wb",
            ) as dst:
                while True:
                    chunk = src.read(
                        CHUNK_SIZE
                    )
                    if not chunk:
                        break

                    digest.update(
                        chunk
                    )
                    dst.write(
                        chunk
                    )
                    restored_bytes += len(
                        chunk
                    )

        if (
            restored_bytes
            != manifest.uncompressed_size_bytes
        ):
            raise RuntimeError(
                "Cold-history materialization size "
                "does not match archive manifest."
            )

        if (
            digest.hexdigest()
            != manifest.uncompressed_sha256
        ):
            raise RuntimeError(
                "Cold-history materialization SHA-256 "
                "does not match archive manifest."
            )

        uri = (
            restored.resolve().as_uri()
            + "?mode=ro&immutable=1"
        )
        conn = sqlite3.connect(
            uri,
            uri=True,
            timeout=30.0,
        )

        try:
            conn.execute(
                "PRAGMA query_only = ON;"
            )

            integrity = str(
                conn.execute(
                    "PRAGMA integrity_check;"
                ).fetchone()[0]
            )

            if integrity != "ok":
                raise RuntimeError(
                    "Cold-history archive "
                    f"integrity_check failed: "
                    f"{integrity}"
                )

            _emit(
                progress,
                "cold-read: verified read-only "
                f"archive ready "
                f"schema_v="
                f"{manifest.source_schema_version}",
            )

            yield (
                manifest,
                conn,
            )

        finally:
            conn.close()


def _encode_value(
    value: object,
) -> bytes:
    if value is None:
        return b"N"

    if isinstance(
        value,
        bool,
    ):
        return (
            b"B1"
            if value
            else b"B0"
        )

    if isinstance(
        value,
        int,
    ):
        payload = str(
            value
        ).encode(
            "ascii"
        )
        return (
            b"I"
            + str(
                len(payload)
            ).encode(
                "ascii"
            )
            + b":"
            + payload
        )

    if isinstance(
        value,
        float,
    ):
        payload = value.hex().encode(
            "ascii"
        )
        return (
            b"F"
            + str(
                len(payload)
            ).encode(
                "ascii"
            )
            + b":"
            + payload
        )

    if isinstance(
        value,
        bytes,
    ):
        return (
            b"Y"
            + str(
                len(value)
            ).encode(
                "ascii"
            )
            + b":"
            + value
        )

    payload = str(
        value
    ).encode(
        "utf-8"
    )

    return (
        b"T"
        + str(
            len(payload)
        ).encode(
            "ascii"
        )
        + b":"
        + payload
    )


def _fingerprint_query(
    conn: sqlite3.Connection,
    *,
    table_name: str,
    sql: str,
    params: tuple[object, ...] = (),
) -> EvidenceTableFingerprint:
    cursor = conn.execute(
        sql,
        params,
    )

    columns = tuple(
        str(item[0])
        for item in (
            cursor.description
            or ()
        )
    )

    digest = hashlib.sha256()
    digest.update(
        b"CHRISTIANIA_EVIDENCE_FINGERPRINT_V1\n"
    )
    digest.update(
        table_name.encode(
            "utf-8"
        )
    )
    digest.update(
        b"\n"
    )

    for column in columns:
        digest.update(
            _encode_value(
                column
            )
        )

    row_count = 0

    while True:
        rows = cursor.fetchmany(
            FINGERPRINT_FETCH_ROWS
        )

        if not rows:
            break

        for row in rows:
            digest.update(
                b"R"
            )

            for value in row:
                encoded = (
                    _encode_value(
                        value
                    )
                )
                digest.update(
                    str(
                        len(encoded)
                    ).encode(
                        "ascii"
                    )
                )
                digest.update(
                    b":"
                )
                digest.update(
                    encoded
                )

            digest.update(
                b"\n"
            )
            row_count += 1

    return EvidenceTableFingerprint(
        table_name=table_name,
        columns=columns,
        row_count=row_count,
        sha256=digest.hexdigest(),
    )


def _archive_table_columns(
    conn: sqlite3.Connection,
    table_name: str,
) -> tuple[str, ...]:
    safe = table_name.replace(
        '"',
        '""',
    )
    rows = conn.execute(
        f'PRAGMA table_info("{safe}");'
    ).fetchall()

    columns = tuple(
        str(row[1])
        for row in rows
    )

    if not columns:
        raise RuntimeError(
            "Cold-history archive table "
            f"has no columns: {table_name}"
        )

    return columns


def _order_clause(
    columns: tuple[str, ...],
) -> str:
    preferred = (
        ("id",)
        if "id" in columns
        else columns
    )

    return ", ".join(
        '"'
        + column.replace(
            '"',
            '""',
        )
        + '"'
        for column in preferred
    )


def _prepare_hot_scope(
    conn: sqlite3.Connection,
    manifest: ResearchArchiveManifest,
) -> int:
    conn.execute(
        """
        CREATE TEMP TABLE _archive_runs(
            id INTEGER PRIMARY KEY
        );
        """
    )

    conn.executemany(
        """
        INSERT INTO _archive_runs(id)
        VALUES(?);
        """,
        (
            (run_id,)
            for run_id
            in manifest.run_ids
        ),
    )

    row = conn.execute(
        """
        SELECT MAX(version)
        FROM source.schema_version;
        """
    ).fetchone()

    if (
        row is None
        or row[0] is None
    ):
        raise RuntimeError(
            "Hot Christiania database has no "
            "schema version."
        )

    return int(
        row[0]
    )


def verify_hot_archive_parity(
    session_date: str,
    *,
    db_path: str | Path | None = None,
    archive_dir: str | Path | None = None,
    progress: Callable[[str], None] | None = None,
) -> ArchiveParityResult:
    database = resolve_db_path(
        db_path
    )

    with open_verified_archive_session(
        session_date,
        archive_dir=archive_dir,
        progress=progress,
    ) as (
        manifest,
        archive_conn,
    ):
        source_uri = (
            database.resolve().as_uri()
            + "?mode=ro"
        )

        hot_conn = sqlite3.connect(
            ":memory:",
            isolation_level=None,
        )

        try:
            hot_conn.execute(
                "ATTACH DATABASE ? AS source;",
                (source_uri,),
            )

            hot_schema_version = (
                _prepare_hot_scope(
                    hot_conn,
                    manifest,
                )
            )

            if (
                hot_schema_version
                != EXPECTED_SCHEMA_VERSION
            ):
                raise RuntimeError(
                    "Hot database schema does not "
                    "match active release: "
                    f"v{hot_schema_version} != "
                    f"v{EXPECTED_SCHEMA_VERSION}."
                )

            parity: list[
                EvidenceTableParity
            ] = []

            for spec in (
                ARCHIVE_TABLE_SPECS
            ):
                columns = (
                    _archive_table_columns(
                        archive_conn,
                        spec.table_name,
                    )
                )
                order_by = (
                    _order_clause(
                        columns
                    )
                )
                safe_table = (
                    spec.table_name.replace(
                        '"',
                        '""',
                    )
                )

                _emit(
                    progress,
                    "parity: fingerprint "
                    f"{spec.table_name} started",
                )

                archive_fp = (
                    _fingerprint_query(
                        archive_conn,
                        table_name=(
                            spec.table_name
                        ),
                        sql=(
                            f'SELECT * FROM '
                            f'"{safe_table}" '
                            f"ORDER BY {order_by};"
                        ),
                    )
                )

                hot_fp = (
                    _fingerprint_query(
                        hot_conn,
                        table_name=(
                            spec.table_name
                        ),
                        sql=(
                            "SELECT * FROM ("
                            + spec.select_sql
                            + ") AS session_rows "
                            + f"ORDER BY {order_by};"
                        ),
                    )
                )

                matches = (
                    hot_fp.columns
                    == archive_fp.columns
                    and hot_fp.row_count
                    == archive_fp.row_count
                    and hot_fp.sha256
                    == archive_fp.sha256
                )

                parity.append(
                    EvidenceTableParity(
                        table_name=(
                            spec.table_name
                        ),
                        hot=hot_fp,
                        archive=archive_fp,
                        matches=matches,
                    )
                )

                _emit(
                    progress,
                    "parity: fingerprint "
                    f"{spec.table_name} "
                    f"{'PASS' if matches else 'FAIL'} "
                    f"rows={hot_fp.row_count}",
                )

        finally:
            hot_conn.close()

    return ArchiveParityResult(
        session_date=session_date,
        run_ids=manifest.run_ids,
        archive_filename=(
            manifest.archive_filename
        ),
        archive_source_schema_version=(
            manifest.source_schema_version
        ),
        hot_schema_version=(
            hot_schema_version
        ),
        tables=tuple(
            parity
        ),
    )


def read_historical_session_profile(
    session_date: str,
    *,
    archive_dir: str | Path | None = None,
    progress: Callable[[str], None] | None = None,
) -> HistoricalSessionProfile:
    with open_verified_archive_session(
        session_date,
        archive_dir=archive_dir,
        progress=progress,
    ) as (
        manifest,
        conn,
    ):
        table_counts = {
            spec.table_name: int(
                conn.execute(
                    "SELECT COUNT(*) "
                    f"FROM {spec.table_name};"
                ).fetchone()[0]
            )
            for spec
            in ARCHIVE_TABLE_SPECS
        }

        quote_row = conn.execute(
            """
            SELECT
                COUNT(*) AS quote_count,
                COUNT(
                    DISTINCT ms.underlying
                ) AS underlying_count,
                COUNT(
                    DISTINCT oq.expiration
                ) AS expiration_count,
                SUM(
                    CASE
                        WHEN oq.bid IS NOT NULL
                         AND oq.ask IS NOT NULL
                        THEN 1
                        ELSE 0
                    END
                ) AS bid_ask_complete_count,
                SUM(
                    CASE
                        WHEN oq.implied_volatility
                             IS NOT NULL
                        THEN 1
                        ELSE 0
                    END
                ) AS iv_count,
                SUM(
                    CASE
                        WHEN oq.delta IS NOT NULL
                        THEN 1
                        ELSE 0
                    END
                ) AS delta_count,
                MIN(oq.quote_at),
                MAX(oq.quote_at)
            FROM option_quotes AS oq
            JOIN market_snapshots AS ms
              ON ms.id = oq.snapshot_id;
            """
        ).fetchone()

        quote_metrics = {
            "quote_count":
                int(quote_row[0] or 0),
            "underlying_count":
                int(quote_row[1] or 0),
            "expiration_count":
                int(quote_row[2] or 0),
            "bid_ask_complete_count":
                int(quote_row[3] or 0),
            "iv_count":
                int(quote_row[4] or 0),
            "delta_count":
                int(quote_row[5] or 0),
            "first_quote_at":
                quote_row[6],
            "last_quote_at":
                quote_row[7],
        }

        provider_model_counts = {
            str(provider):
                int(count)
            for (
                provider,
                count,
            ) in conn.execute(
                """
                SELECT
                    provider,
                    COUNT(*)
                FROM provider_model_observations
                GROUP BY provider
                ORDER BY provider;
                """
            ).fetchall()
        }

        scanner_state_counts = {
            str(state):
                int(count)
            for (
                state,
                count,
            ) in conn.execute(
                """
                SELECT
                    evaluation_state,
                    COUNT(*)
                FROM hypothesis_scanner_evaluations
                GROUP BY evaluation_state
                ORDER BY evaluation_state;
                """
            ).fetchall()
        }

        surface_state_counts = {
            str(state):
                int(count)
            for (
                state,
                count,
            ) in conn.execute(
                """
                SELECT
                    observation_state,
                    COUNT(*)
                FROM local_surface_residual_v2_observations
                GROUP BY observation_state
                ORDER BY observation_state;
                """
            ).fetchall()
        }

        return HistoricalSessionProfile(
            session_date=(
                manifest.session_date
            ),
            run_ids=manifest.run_ids,
            archive_filename=(
                manifest.archive_filename
            ),
            archive_source_schema_version=(
                manifest.source_schema_version
            ),
            table_counts=table_counts,
            quote_metrics=quote_metrics,
            provider_model_counts=(
                provider_model_counts
            ),
            scanner_state_counts=(
                scanner_state_counts
            ),
            surface_state_counts=(
                surface_state_counts
            ),
        )
