from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from time import monotonic
from typing import Callable

from src.database.repository import resolve_db_path


@dataclass(frozen=True)
class StorageObject:
    name: str
    object_type: str
    bytes: int
    pages: int

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class StorageAudit:
    database_path: str
    database_size_bytes: int
    page_size_bytes: int
    page_count: int
    freelist_pages: int
    freelist_bytes: int
    object_attribution_state: str
    object_attribution_detail: str
    object_attribution_elapsed_seconds: float
    objects: tuple[StorageObject, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            **asdict(self),
            "objects": [
                item.as_dict()
                for item in self.objects
            ],
        }


def audit_storage(
    db_path: str | Path | None = None,
    *,
    progress: Callable[[str], None] | None = None,
    progress_interval_seconds: float = 5.0,
) -> StorageAudit:
    path = resolve_db_path(db_path)
    if not path.is_file():
        raise FileNotFoundError(
            f"Christiania database not found: {path}"
        )

    if progress_interval_seconds <= 0:
        raise ValueError(
            "progress_interval_seconds must be positive."
        )

    uri = path.resolve().as_uri() + "?mode=ro"
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
        freelist = int(
            conn.execute(
                "PRAGMA freelist_count;"
            ).fetchone()[0]
        )

        started = monotonic()
        last_progress = started

        def report_progress() -> int:
            nonlocal last_progress

            if progress is None:
                return 0

            current = monotonic()
            if (
                current - last_progress
                >= progress_interval_seconds
            ):
                progress(
                    "dbstat attribution still running; "
                    f"elapsed={current - started:.1f}s"
                )
                last_progress = current

            return 0

        if progress is not None:
            progress(
                "dbstat attribution started; "
                f"database_bytes={path.stat().st_size}"
            )

        conn.set_progress_handler(
            report_progress,
            100_000,
        )

        try:
            rows = conn.execute(
                """
                SELECT
                    d.name,
                    COALESCE(m.type, 'internal') AS object_type,
                    SUM(d.pgsize) AS bytes,
                    COUNT(*) AS pages
                FROM dbstat AS d
                LEFT JOIN sqlite_master AS m
                  ON m.name = d.name
                GROUP BY
                    d.name,
                    COALESCE(m.type, 'internal')
                ORDER BY
                    bytes DESC,
                    d.name;
                """
            ).fetchall()
        except sqlite3.Error as exc:
            rows = []
            attribution_state = "UNAVAILABLE_DBSTAT"
            attribution_detail = (
                "SQLite dbstat virtual table is unavailable: "
                f"{type(exc).__name__}:{exc}"
            )
        else:
            attribution_state = "AVAILABLE"
            attribution_detail = (
                "SQLite dbstat object attribution available."
            )
        finally:
            conn.set_progress_handler(
                None,
                0,
            )

        attribution_elapsed = (
            monotonic() - started
        )

        if progress is not None:
            progress(
                "dbstat attribution finished; "
                f"state={attribution_state}; "
                f"elapsed={attribution_elapsed:.1f}s; "
                f"objects={len(rows)}"
            )
    finally:
        conn.close()

    objects = tuple(
        StorageObject(
            name=str(row[0]),
            object_type=str(row[1]),
            bytes=int(row[2] or 0),
            pages=int(row[3] or 0),
        )
        for row in rows
    )

    return StorageAudit(
        database_path=str(path),
        database_size_bytes=path.stat().st_size,
        page_size_bytes=page_size,
        page_count=page_count,
        freelist_pages=freelist,
        freelist_bytes=freelist * page_size,
        object_attribution_state=attribution_state,
        object_attribution_detail=attribution_detail,
        object_attribution_elapsed_seconds=attribution_elapsed,
        objects=objects,
    )
