from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import struct
import tempfile
from typing import Callable, Iterator

from src.database.repository import (
    EXPECTED_SCHEMA_VERSION,
    resolve_db_path,
)
from src.operations.sqlite_runtime import (
    backup_required_free_bytes,
)
from src.operations.research_archive import (
    ARCHIVE_TABLE_SPECS,
    CHUNK_SIZE,
    ResearchArchiveManifest,
    inventory_research_archives,
    resolve_archive_dir,
    verify_research_archive,
)


ARCHIVE_PARITY_FORMAT_VERSION = 1
ARCHIVE_PARITY_STATE = (
    "HOT_COLD_CONTENT_PARITY_VERIFIED"
)
FINGERPRINT_PROGRESS_ROWS = 100_000


@dataclass(frozen=True)
class TableContentFingerprint:
    table_name: str
    row_count: int
    column_names: tuple[str, ...]
    content_sha256: str

    def as_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["column_names"] = list(
            self.column_names
        )
        return data


@dataclass(frozen=True)
class ArchiveParityReceipt:
    format_version: int
    state: str
    verified_at: str
    session_date: str
    run_ids: tuple[int, ...]
    archive_manifest_filename: str
    archive_manifest_sha256: str
    archive_compressed_sha256: str
    archive_uncompressed_sha256: str
    archive_source_schema_version: int
    current_schema_version: int
    hot_fingerprints: dict[
        str,
        TableContentFingerprint,
    ]
    archive_fingerprints: dict[
        str,
        TableContentFingerprint,
    ]
    content_parity: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "format_version":
                self.format_version,
            "state": self.state,
            "verified_at":
                self.verified_at,
            "session_date":
                self.session_date,
            "run_ids":
                list(self.run_ids),
            "archive_manifest_filename":
                self.archive_manifest_filename,
            "archive_manifest_sha256":
                self.archive_manifest_sha256,
            "archive_compressed_sha256":
                self.archive_compressed_sha256,
            "archive_uncompressed_sha256":
                self.archive_uncompressed_sha256,
            "archive_source_schema_version":
                self.archive_source_schema_version,
            "current_schema_version":
                self.current_schema_version,
            "hot_fingerprints": {
                name: fingerprint.as_dict()
                for name, fingerprint
                in self.hot_fingerprints.items()
            },
            "archive_fingerprints": {
                name: fingerprint.as_dict()
                for name, fingerprint
                in self.archive_fingerprints.items()
            },
            "content_parity":
                self.content_parity,
        }


@dataclass(frozen=True)
class ArchivedSessionProfile:
    session_date: str
    run_ids: tuple[int, ...]
    archive_filename: str
    archive_source_schema_version: int
    table_counts: dict[str, int]
    option_quote_universe: dict[str, object]
    provider_model_rows_by_provider: dict[str, int]
    scanner_rows_by_state: dict[str, int]

    def as_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["run_ids"] = list(
            self.run_ids
        )
        return data


@dataclass
class VerifiedArchiveSession:
    manifest: ResearchArchiveManifest
    manifest_path: Path
    materialized_path: Path
    connection: sqlite3.Connection


def _emit(
    progress: Callable[[str], None] | None,
    message: str,
) -> None:
    if progress is not None:
        progress(message)


def _sha256_file(
    path: Path,
) -> str:
    digest = hashlib.sha256()

    with path.open(
        "rb"
    ) as handle:
        while True:
            chunk = handle.read(
                CHUNK_SIZE
            )

            if not chunk:
                break

            digest.update(
                chunk
            )

    return digest.hexdigest()


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
            handle.write(
                text
            )
            handle.flush()
            os.fsync(
                handle.fileno()
            )

        os.replace(
            temp,
            path,
        )

        if os.name != "nt":
            flags = (
                os.O_RDONLY
                | getattr(
                    os,
                    "O_DIRECTORY",
                    0,
                )
            )

            fd = os.open(
                path.parent,
                flags,
            )

            try:
                os.fsync(
                    fd
                )
            finally:
                os.close(
                    fd
                )
    finally:
        if temp.exists():
            temp.unlink()


def _manifest_for_session(
    session_date: str,
    archive_dir: Path,
) -> tuple[
    Path,
    ResearchArchiveManifest,
]:
    inventory = (
        inventory_research_archives(
            archive_dir
        )
    )

    matches = [
        manifest
        for manifest
        in inventory.manifests
        if (
            manifest.session_date
            == session_date
        )
    ]

    if not matches:
        raise FileNotFoundError(
            "No verified research archive "
            f"exists for session {session_date}."
        )

    if len(matches) != 1:
        raise RuntimeError(
            "Expected exactly one research "
            f"archive for {session_date}; "
            f"found {len(matches)}."
        )

    manifest = matches[0]

    return (
        archive_dir
        / manifest.manifest_filename,
        manifest,
    )


def parity_receipt_path(
    manifest_path: str | Path,
) -> Path:
    path = Path(
        manifest_path
    ).expanduser()

    suffix = ".manifest.json"

    if not path.name.endswith(
        suffix
    ):
        raise ValueError(
            "Unexpected archive manifest "
            "filename."
        )

    return path.with_name(
        path.name[
            :-len(suffix)
        ]
        + ".parity-receipt.json"
    )


def _current_schema_version(
    database: Path,
) -> int:
    uri = (
        database.resolve().as_uri()
        + "?mode=ro"
    )

    conn = sqlite3.connect(
        uri,
        uri=True,
        timeout=30.0,
    )

    try:
        row = conn.execute(
            """
            SELECT MAX(version)
            FROM schema_version;
            """
        ).fetchone()

        if (
            row is None
            or row[0] is None
        ):
            raise RuntimeError(
                "Christiania database has no "
                "schema version."
            )

        return int(
            row[0]
        )
    finally:
        conn.close()


def _validate_archive_metadata(
    conn: sqlite3.Connection,
    manifest: ResearchArchiveManifest,
) -> None:
    rows = conn.execute(
        """
        SELECT key, value
        FROM archive_metadata;
        """
    ).fetchall()

    metadata = {
        str(key): str(value)
        for key, value
        in rows
    }

    expected = {
        "format_version":
            str(
                manifest.format_version
            ),
        "coverage":
            manifest.coverage,
        "session_date":
            manifest.session_date,
        "run_ids_json":
            json.dumps(
                list(
                    manifest.run_ids
                ),
                separators=(
                    ",",
                    ":",
                ),
            ),
        "source_schema_version":
            str(
                manifest.source_schema_version
            ),
    }

    for (
        key,
        value,
    ) in expected.items():
        if metadata.get(
            key
        ) != value:
            raise RuntimeError(
                "Archive metadata mismatch "
                f"for {key}: "
                f"{metadata.get(key)!r} "
                f"!= {value!r}."
            )


@contextmanager
def open_verified_archive_session(
    session_date: str,
    *,
    archive_dir: str | Path | None = None,
    progress: Callable[[str], None] | None = None,
) -> Iterator[
    VerifiedArchiveSession
]:
    directory = (
        resolve_archive_dir(
            archive_dir
        )
    )

    (
        manifest_path,
        manifest,
    ) = _manifest_for_session(
        session_date,
        directory,
    )

    _emit(
        progress,
        "archive-read: compressed "
        "payload verification started",
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
        prefix=(
            "christiania-verified-archive-"
        )
    ) as temp_dir:
        restored = (
            Path(
                temp_dir
            )
            / "archive.db"
        )

        usage = shutil.disk_usage(
            temp_dir
        )
        # Cold parity/profile queries may require a temporary sort
        # because archive tables intentionally carry no production indexes.
        # Reserve one uncompressed archive for materialization and a second
        # full-size allowance for SQLite query/sort workspace, in addition to
        # the normal Christiania filesystem reserve.
        materialization_and_workspace = (
            manifest.uncompressed_size_bytes
            * 2
        )

        required_free = (
            backup_required_free_bytes(
                source_size_bytes=(
                    materialization_and_workspace
                ),
                filesystem_total_bytes=int(
                    usage.total
                ),
            )
        )

        if int(
            usage.free
        ) < required_free:
            raise RuntimeError(
                "Insufficient temporary "
                "filesystem headroom for "
                "verified archive "
                "materialization: "
                f"free={int(usage.free)} "
                f"required={required_free} "
                "uncompressed_archive="
                f"{manifest.uncompressed_size_bytes} "
                "materialization_and_workspace="
                f"{materialization_and_workspace}."
            )

        digest = hashlib.sha256()
        restored_bytes = 0

        _emit(
            progress,
            "archive-read: materialization "
            "started",
        )

        with gzip.open(
            archive_path,
            "rb",
        ) as source:
            with restored.open(
                "wb"
            ) as target:
                while True:
                    chunk = source.read(
                        CHUNK_SIZE
                    )

                    if not chunk:
                        break

                    next_size = (
                        restored_bytes
                        + len(
                            chunk
                        )
                    )

                    if (
                        next_size
                        > manifest.uncompressed_size_bytes
                    ):
                        raise RuntimeError(
                            "Materialized archive "
                            "exceeded manifest "
                            "uncompressed size."
                        )

                    digest.update(
                        chunk
                    )
                    target.write(
                        chunk
                    )
                    restored_bytes = (
                        next_size
                    )

        if (
            restored_bytes
            != manifest.uncompressed_size_bytes
        ):
            raise RuntimeError(
                "Materialized archive size "
                "does not match manifest."
            )

        if (
            digest.hexdigest()
            != manifest.uncompressed_sha256
        ):
            raise RuntimeError(
                "Materialized archive SHA-256 "
                "does not match manifest."
            )

        _emit(
            progress,
            "archive-read: materialization "
            f"complete bytes={restored_bytes}",
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
            conn.row_factory = (
                sqlite3.Row
            )

            integrity = str(
                conn.execute(
                    """
                    PRAGMA integrity_check;
                    """
                ).fetchone()[0]
            )

            if integrity != "ok":
                raise RuntimeError(
                    "Materialized archive "
                    "integrity_check failed: "
                    f"{integrity}"
                )

            _validate_archive_metadata(
                conn,
                manifest,
            )

            conn.execute(
                "PRAGMA query_only = ON;"
            )

            _emit(
                progress,
                "archive-read: verified "
                "read-only session ready",
            )

            yield VerifiedArchiveSession(
                manifest=manifest,
                manifest_path=(
                    manifest_path
                ),
                materialized_path=(
                    restored
                ),
                connection=conn,
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
            b"I1"
            if value
            else b"I0"
        )

    if isinstance(
        value,
        int,
    ):
        return (
            b"I"
            + str(
                value
            ).encode(
                "ascii"
            )
        )

    if isinstance(
        value,
        float,
    ):
        return (
            b"F"
            + struct.pack(
                ">d",
                value,
            )
        )

    if isinstance(
        value,
        str,
    ):
        return (
            b"T"
            + value.encode(
                "utf-8"
            )
        )

    if isinstance(
        value,
        (
            bytes,
            bytearray,
            memoryview,
        ),
    ):
        return (
            b"B"
            + bytes(
                value
            )
        )

    raise TypeError(
        "Unsupported SQLite value type "
        f"for parity fingerprint: "
        f"{type(value).__name__}"
    )


def _query_columns(
    conn: sqlite3.Connection,
    base_sql: str,
) -> tuple[str, ...]:
    cursor = conn.execute(
        "SELECT * FROM ("
        + base_sql
        + ") AS fingerprint_source "
        "LIMIT 0;"
    )

    if cursor.description is None:
        raise RuntimeError(
            "Fingerprint query produced "
            "no column metadata."
        )

    return tuple(
        str(
            item[0]
        )
        for item
        in cursor.description
    )


def _quote_column(
    column: str,
) -> str:
    return (
        '"'
        + column.replace(
            '"',
            '""',
        )
        + '"'
    )


def _ordered_query(
    conn: sqlite3.Connection,
    base_sql: str,
) -> tuple[
    str,
    tuple[str, ...],
]:
    columns = _query_columns(
        conn,
        base_sql,
    )

    if not columns:
        raise RuntimeError(
            "Fingerprint query has no columns."
        )

    if "id" in columns:
        ordering = '"id"'
    else:
        ordering = ", ".join(
            _quote_column(
                column
            )
            for column
            in columns
        )

    return (
        "SELECT * FROM ("
        + base_sql
        + ") AS fingerprint_source "
        + "ORDER BY "
        + ordering
        + ";",
        columns,
    )


def _fingerprint_query(
    conn: sqlite3.Connection,
    *,
    table_name: str,
    base_sql: str,
    progress: Callable[[str], None] | None = None,
    phase: str,
) -> TableContentFingerprint:
    (
        ordered_sql,
        columns,
    ) = _ordered_query(
        conn,
        base_sql,
    )

    digest = hashlib.sha256()

    digest.update(
        b"CHRISTIANIA_TABLE_FINGERPRINT_V1\x00"
    )

    for column in columns:
        payload = column.encode(
            "utf-8"
        )

        digest.update(
            len(payload).to_bytes(
                8,
                "big",
            )
        )
        digest.update(
            payload
        )

    cursor = conn.execute(
        ordered_sql
    )

    row_count = 0

    for row in cursor:
        digest.update(
            b"R"
        )

        for value in row:
            payload = _encode_value(
                value
            )

            digest.update(
                len(payload).to_bytes(
                    8,
                    "big",
                )
            )
            digest.update(
                payload
            )

        row_count += 1

        if (
            progress is not None
            and row_count
            % FINGERPRINT_PROGRESS_ROWS
            == 0
        ):
            progress(
                "archive-parity: "
                f"{phase} {table_name} "
                f"rows={row_count}"
            )

    _emit(
        progress,
        "archive-parity: "
        f"{phase} {table_name} "
        f"complete rows={row_count}",
    )

    return TableContentFingerprint(
        table_name=table_name,
        row_count=row_count,
        column_names=columns,
        content_sha256=(
            digest.hexdigest()
        ),
    )


def _hot_fingerprints(
    database: Path,
    manifest: ResearchArchiveManifest,
    *,
    progress: Callable[[str], None] | None,
) -> dict[
    str,
    TableContentFingerprint,
]:
    source_uri = (
        database.resolve().as_uri()
        + "?mode=ro"
    )

    conn = sqlite3.connect(
        ":memory:",
        uri=True,
        timeout=60.0,
        isolation_level=None,
    )

    try:
        conn.execute(
            "ATTACH DATABASE ? AS source;",
            (
                source_uri,
            ),
        )

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
                (
                    int(
                        run_id
                    ),
                )
                for run_id
                in manifest.run_ids
            ),
        )

        result: dict[
            str,
            TableContentFingerprint,
        ] = {}

        for spec in (
            ARCHIVE_TABLE_SPECS
        ):
            result[
                spec.table_name
            ] = _fingerprint_query(
                conn,
                table_name=(
                    spec.table_name
                ),
                base_sql=(
                    spec.select_sql
                ),
                progress=progress,
                phase="hot",
            )

        return result
    finally:
        conn.close()


def _archive_fingerprints(
    conn: sqlite3.Connection,
    *,
    progress: Callable[[str], None] | None,
) -> dict[
    str,
    TableContentFingerprint,
]:
    result: dict[
        str,
        TableContentFingerprint,
    ] = {}

    for spec in (
        ARCHIVE_TABLE_SPECS
    ):
        table_name = (
            spec.table_name
        )

        base_sql = (
            "SELECT * FROM "
            + _quote_column(
                table_name
            )
        )

        result[
            table_name
        ] = _fingerprint_query(
            conn,
            table_name=(
                table_name
            ),
            base_sql=base_sql,
            progress=progress,
            phase="archive",
        )

    return result


def _fingerprints_equal(
    hot: dict[
        str,
        TableContentFingerprint,
    ],
    archive: dict[
        str,
        TableContentFingerprint,
    ],
) -> bool:
    if set(
        hot
    ) != set(
        archive
    ):
        return False

    for table_name in hot:
        if (
            hot[
                table_name
            ]
            != archive[
                table_name
            ]
        ):
            return False

    return True


def verify_archive_session_parity(
    session_date: str,
    *,
    db_path: str | Path | None = None,
    archive_dir: str | Path | None = None,
    persist: bool = True,
    progress: Callable[[str], None] | None = None,
) -> ArchiveParityReceipt:
    database = resolve_db_path(
        db_path
    )

    directory = (
        resolve_archive_dir(
            archive_dir
        )
    )

    (
        manifest_path,
        manifest,
    ) = _manifest_for_session(
        session_date,
        directory,
    )

    schema_version = (
        _current_schema_version(
            database
        )
    )

    if (
        schema_version
        != EXPECTED_SCHEMA_VERSION
    ):
        raise RuntimeError(
            "Current database schema does not "
            "match the active release: "
            f"v{schema_version} != "
            f"v{EXPECTED_SCHEMA_VERSION}."
        )

    _emit(
        progress,
        "archive-parity: hot evidence "
        "fingerprint started",
    )

    hot = _hot_fingerprints(
        database,
        manifest,
        progress=progress,
    )

    _emit(
        progress,
        "archive-parity: cold evidence "
        "fingerprint started",
    )

    with open_verified_archive_session(
        session_date,
        archive_dir=directory,
        progress=progress,
    ) as archive:
        cold = _archive_fingerprints(
            archive.connection,
            progress=progress,
        )

    parity = _fingerprints_equal(
        hot,
        cold,
    )

    count_mismatches = [
        (
            table_name,
            int(
                manifest.table_counts.get(
                    table_name,
                    -1,
                )
            ),
            hot[
                table_name
            ].row_count,
            cold[
                table_name
            ].row_count,
        )
        for table_name
        in sorted(
            hot
        )
        if (
            hot[
                table_name
            ].row_count
            != int(
                manifest.table_counts.get(
                    table_name,
                    -1,
                )
            )
            or cold[
                table_name
            ].row_count
            != int(
                manifest.table_counts.get(
                    table_name,
                    -1,
                )
            )
        )
    ]

    if count_mismatches:
        raise RuntimeError(
            "Hot/cold fingerprint counts "
            "do not match archive manifest: "
            + "; ".join(
                (
                    f"{table}:"
                    f"manifest={expected}:"
                    f"hot={hot_count}:"
                    f"archive={cold_count}"
                )
                for (
                    table,
                    expected,
                    hot_count,
                    cold_count,
                )
                in count_mismatches
            )
        )

    if not parity:
        mismatches = [
            table_name
            for table_name
            in sorted(
                set(hot)
                | set(cold)
            )
            if (
                hot.get(
                    table_name
                )
                != cold.get(
                    table_name
                )
            )
        ]

        raise RuntimeError(
            "Hot/cold research evidence "
            "parity failed for: "
            + ", ".join(
                mismatches
            )
        )

    receipt = ArchiveParityReceipt(
        format_version=(
            ARCHIVE_PARITY_FORMAT_VERSION
        ),
        state=(
            ARCHIVE_PARITY_STATE
        ),
        verified_at=(
            datetime.now(
                UTC
            )
            .isoformat()
            .replace(
                "+00:00",
                "Z",
            )
        ),
        session_date=(
            manifest.session_date
        ),
        run_ids=(
            manifest.run_ids
        ),
        archive_manifest_filename=(
            manifest.manifest_filename
        ),
        archive_manifest_sha256=(
            _sha256_file(
                manifest_path
            )
        ),
        archive_compressed_sha256=(
            manifest.compressed_sha256
        ),
        archive_uncompressed_sha256=(
            manifest.uncompressed_sha256
        ),
        archive_source_schema_version=(
            manifest.source_schema_version
        ),
        current_schema_version=(
            schema_version
        ),
        hot_fingerprints=hot,
        archive_fingerprints=cold,
        content_parity=True,
    )

    if persist:
        receipt_path = (
            parity_receipt_path(
                manifest_path
            )
        )

        _write_json_atomic(
            receipt_path,
            receipt.as_dict(),
        )

        _emit(
            progress,
            "archive-parity: receipt "
            f"written {receipt_path}",
        )

    return receipt


def _fingerprint_from_dict(
    payload: dict[str, object],
) -> TableContentFingerprint:
    return TableContentFingerprint(
        table_name=str(
            payload[
                "table_name"
            ]
        ),
        row_count=int(
            payload[
                "row_count"
            ]
        ),
        column_names=tuple(
            str(
                item
            )
            for item
            in payload[
                "column_names"
            ]
        ),
        content_sha256=str(
            payload[
                "content_sha256"
            ]
        ),
    )


def load_archive_parity_receipt(
    path: str | Path,
) -> ArchiveParityReceipt:
    receipt_path = Path(
        path
    ).expanduser()

    payload = json.loads(
        receipt_path.read_text(
            encoding="utf-8"
        )
    )

    hot = {
        str(
            name
        ): _fingerprint_from_dict(
            dict(
                value
            )
        )
        for name, value
        in dict(
            payload[
                "hot_fingerprints"
            ]
        ).items()
    }

    cold = {
        str(
            name
        ): _fingerprint_from_dict(
            dict(
                value
            )
        )
        for name, value
        in dict(
            payload[
                "archive_fingerprints"
            ]
        ).items()
    }

    return ArchiveParityReceipt(
        format_version=int(
            payload[
                "format_version"
            ]
        ),
        state=str(
            payload[
                "state"
            ]
        ),
        verified_at=str(
            payload[
                "verified_at"
            ]
        ),
        session_date=str(
            payload[
                "session_date"
            ]
        ),
        run_ids=tuple(
            int(
                item
            )
            for item
            in payload[
                "run_ids"
            ]
        ),
        archive_manifest_filename=str(
            payload[
                "archive_manifest_filename"
            ]
        ),
        archive_manifest_sha256=str(
            payload[
                "archive_manifest_sha256"
            ]
        ),
        archive_compressed_sha256=str(
            payload[
                "archive_compressed_sha256"
            ]
        ),
        archive_uncompressed_sha256=str(
            payload[
                "archive_uncompressed_sha256"
            ]
        ),
        archive_source_schema_version=int(
            payload[
                "archive_source_schema_version"
            ]
        ),
        current_schema_version=int(
            payload[
                "current_schema_version"
            ]
        ),
        hot_fingerprints=hot,
        archive_fingerprints=cold,
        content_parity=bool(
            payload[
                "content_parity"
            ]
        ),
    )


def validate_archive_parity_receipt(
    session_date: str,
    *,
    db_path: str | Path | None = None,
    archive_dir: str | Path | None = None,
) -> ArchiveParityReceipt:
    database = resolve_db_path(
        db_path
    )

    directory = (
        resolve_archive_dir(
            archive_dir
        )
    )

    (
        manifest_path,
        manifest,
    ) = _manifest_for_session(
        session_date,
        directory,
    )

    receipt_path = (
        parity_receipt_path(
            manifest_path
        )
    )

    if not receipt_path.is_file():
        raise FileNotFoundError(
            "No hot/cold parity receipt "
            "exists for session "
            f"{session_date}."
        )

    receipt = (
        load_archive_parity_receipt(
            receipt_path
        )
    )

    current_schema = (
        _current_schema_version(
            database
        )
    )

    if (
        receipt.format_version
        != ARCHIVE_PARITY_FORMAT_VERSION
    ):
        raise RuntimeError(
            "Unsupported archive parity "
            "receipt format."
        )

    if (
        receipt.state
        != ARCHIVE_PARITY_STATE
        or not receipt.content_parity
    ):
        raise RuntimeError(
            "Archive parity receipt is "
            "not in a verified state."
        )

    if (
        receipt.session_date
        != manifest.session_date
        or receipt.run_ids
        != manifest.run_ids
    ):
        raise RuntimeError(
            "Archive parity receipt run "
            "lineage does not match manifest."
        )

    if (
        receipt.archive_manifest_filename
        != manifest.manifest_filename
    ):
        raise RuntimeError(
            "Archive parity receipt manifest "
            "filename mismatch."
        )

    if (
        receipt.archive_manifest_sha256
        != _sha256_file(
            manifest_path
        )
    ):
        raise RuntimeError(
            "Archive parity receipt is not "
            "bound to current manifest bytes."
        )

    if (
        receipt.archive_compressed_sha256
        != manifest.compressed_sha256
        or
        receipt.archive_uncompressed_sha256
        != manifest.uncompressed_sha256
    ):
        raise RuntimeError(
            "Archive parity receipt payload "
            "hashes do not match manifest."
        )

    if (
        receipt.archive_source_schema_version
        != manifest.source_schema_version
    ):
        raise RuntimeError(
            "Archive parity receipt source "
            "schema mismatch."
        )

    if (
        current_schema
        != EXPECTED_SCHEMA_VERSION
        or
        receipt.current_schema_version
        != current_schema
    ):
        raise RuntimeError(
            "Archive parity receipt is stale "
            "for the active database schema."
        )

    expected_tables = {
        spec.table_name
        for spec
        in ARCHIVE_TABLE_SPECS
    }

    if (
        set(
            receipt.hot_fingerprints
        )
        != expected_tables
        or set(
            receipt.archive_fingerprints
        )
        != expected_tables
    ):
        raise RuntimeError(
            "Archive parity receipt does not "
            "cover the complete archive table "
            "contract."
        )

    if not _fingerprints_equal(
        receipt.hot_fingerprints,
        receipt.archive_fingerprints,
    ):
        raise RuntimeError(
            "Archive parity receipt contains "
            "non-matching fingerprints."
        )

    for table_name in (
        expected_tables
    ):
        expected_count = int(
            manifest.table_counts.get(
                table_name,
                -1,
            )
        )

        if (
            receipt.hot_fingerprints[
                table_name
            ].row_count
            != expected_count
            or receipt.archive_fingerprints[
                table_name
            ].row_count
            != expected_count
        ):
            raise RuntimeError(
                "Archive parity receipt row "
                "count does not match manifest "
                f"for {table_name}."
            )

    return receipt


def read_archived_session_profile(
    session_date: str,
    *,
    archive_dir: str | Path | None = None,
    progress: Callable[[str], None] | None = None,
) -> ArchivedSessionProfile:
    with open_verified_archive_session(
        session_date,
        archive_dir=archive_dir,
        progress=progress,
    ) as archive:
        conn = archive.connection

        table_counts = {
            spec.table_name: int(
                conn.execute(
                    "SELECT COUNT(*) FROM "
                    + _quote_column(
                        spec.table_name
                    )
                    + ";"
                ).fetchone()[0]
            )
            for spec in (
                ARCHIVE_TABLE_SPECS
            )
        }

        quote_row = conn.execute(
            """
            SELECT
                COUNT(*) AS row_count,
                COUNT(
                    DISTINCT ms.underlying
                ) AS underlying_count,
                MIN(oq.quote_at)
                    AS first_quote_at,
                MAX(oq.quote_at)
                    AS last_quote_at,
                SUM(
                    CASE
                        WHEN oq.bid
                        IS NOT NULL
                        THEN 1
                        ELSE 0
                    END
                ) AS bid_rows,
                SUM(
                    CASE
                        WHEN oq.ask
                        IS NOT NULL
                        THEN 1
                        ELSE 0
                    END
                ) AS ask_rows,
                SUM(
                    CASE
                        WHEN oq.implied_volatility
                        IS NOT NULL
                        THEN 1
                        ELSE 0
                    END
                ) AS iv_rows,
                SUM(
                    CASE
                        WHEN oq.delta
                        IS NOT NULL
                        THEN 1
                        ELSE 0
                    END
                ) AS delta_rows
            FROM option_quotes AS oq
            JOIN market_snapshots AS ms
              ON ms.id = oq.snapshot_id;
            """
        ).fetchone()

        quote_universe = {
            "row_count":
                int(
                    quote_row[
                        "row_count"
                    ]
                    or 0
                ),
            "underlying_count":
                int(
                    quote_row[
                        "underlying_count"
                    ]
                    or 0
                ),
            "first_quote_at":
                quote_row[
                    "first_quote_at"
                ],
            "last_quote_at":
                quote_row[
                    "last_quote_at"
                ],
            "bid_rows":
                int(
                    quote_row[
                        "bid_rows"
                    ]
                    or 0
                ),
            "ask_rows":
                int(
                    quote_row[
                        "ask_rows"
                    ]
                    or 0
                ),
            "iv_rows":
                int(
                    quote_row[
                        "iv_rows"
                    ]
                    or 0
                ),
            "delta_rows":
                int(
                    quote_row[
                        "delta_rows"
                    ]
                    or 0
                ),
        }

        providers = {
            str(
                row[
                    "provider"
                ]
            ): int(
                row[
                    "row_count"
                ]
            )
            for row
            in conn.execute(
                """
                SELECT
                    provider,
                    COUNT(*) AS row_count
                FROM provider_model_observations
                GROUP BY provider
                ORDER BY provider;
                """
            ).fetchall()
        }

        scanner_states = {
            str(
                row[
                    "evaluation_state"
                ]
            ): int(
                row[
                    "row_count"
                ]
            )
            for row
            in conn.execute(
                """
                SELECT
                    evaluation_state,
                    COUNT(*) AS row_count
                FROM hypothesis_scanner_evaluations
                GROUP BY evaluation_state
                ORDER BY evaluation_state;
                """
            ).fetchall()
        }

        return ArchivedSessionProfile(
            session_date=(
                archive.manifest.session_date
            ),
            run_ids=(
                archive.manifest.run_ids
            ),
            archive_filename=(
                archive.manifest.archive_filename
            ),
            archive_source_schema_version=(
                archive.manifest.source_schema_version
            ),
            table_counts=(
                table_counts
            ),
            option_quote_universe=(
                quote_universe
            ),
            provider_model_rows_by_provider=(
                providers
            ),
            scanner_rows_by_state=(
                scanner_states
            ),
        )
