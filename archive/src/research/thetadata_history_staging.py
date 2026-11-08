from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS thetadata_eod_runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    trading_date TEXT NOT NULL,
    requested_max_dte INTEGER NOT NULL,
    started_at_utc TEXT NOT NULL,
    completed_at_utc TEXT,
    status TEXT NOT NULL CHECK (status IN ('RUNNING', 'COMPLETED', 'FAILED')),
    row_count INTEGER,
    error_text TEXT,
    UNIQUE(symbol, trading_date, requested_max_dte)
);

CREATE TABLE IF NOT EXISTS thetadata_eod_option_rows (
    row_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES thetadata_eod_runs(run_id),
    provider TEXT NOT NULL CHECK (provider = 'THETADATA'),
    underlying TEXT NOT NULL,
    expiration TEXT NOT NULL,
    strike REAL NOT NULL,
    right TEXT NOT NULL CHECK (right IN ('CALL', 'PUT')),

    bid REAL,
    ask REAL,
    bid_size REAL,
    ask_size REAL,
    bid_exchange INTEGER,
    ask_exchange INTEGER,
    bid_condition INTEGER,
    ask_condition INTEGER,

    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume REAL,
    count REAL,

    provider_created TEXT,
    provider_last_trade TEXT,

    raw_json TEXT NOT NULL,

    UNIQUE(run_id, underlying, expiration, strike, right)
);

CREATE INDEX IF NOT EXISTS idx_theta_stage_identity
ON thetadata_eod_option_rows(
    underlying,
    expiration,
    strike,
    right
);

CREATE INDEX IF NOT EXISTS idx_theta_stage_run
ON thetadata_eod_option_rows(run_id);

CREATE INDEX IF NOT EXISTS idx_theta_stage_created
ON thetadata_eod_option_rows(provider_created);

CREATE TABLE IF NOT EXISTS thetadata_eod_revision_collisions (
    collision_id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    trading_date TEXT NOT NULL,
    requested_max_dte INTEGER NOT NULL,
    detected_at_utc TEXT NOT NULL,
    note TEXT NOT NULL
);

"""


@dataclass(frozen=True)
class StagingRunResult:
    run_id: int
    inserted_rows: int


def initialize_staging_db(path: str | Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(SCHEMA_SQL)


def reset_failed_run(
    connection: sqlite3.Connection,
    *,
    run_id: int,
    started_at_utc: str,
) -> None:
    """Explicitly retry a FAILED/RUNNING staging run without silent overwrite."""
    connection.execute(
        "DELETE FROM thetadata_eod_option_rows WHERE run_id = ?",
        (run_id,),
    )
    connection.execute(
        """
        UPDATE thetadata_eod_runs
        SET started_at_utc=?, completed_at_utc=NULL, status='RUNNING',
            row_count=NULL, error_text=NULL
        WHERE run_id=?
        """,
        (started_at_utc, run_id),
    )


def create_run(
    connection: sqlite3.Connection,
    *,
    symbol: str,
    trading_date: date,
    max_dte: int,
    started_at_utc: str,
) -> int:
    cursor = connection.execute(
        """
        INSERT INTO thetadata_eod_runs(
            symbol,
            trading_date,
            requested_max_dte,
            started_at_utc,
            status
        )
        VALUES (?, ?, ?, ?, 'RUNNING')
        """,
        (
            symbol.upper(),
            trading_date.isoformat(),
            max_dte,
            started_at_utc,
        ),
    )
    return int(cursor.lastrowid)


def flatten_for_insert(
    run_id: int,
    row: Mapping[str, Any],
) -> tuple[object, ...]:
    required = (
        "provider",
        "underlying",
        "expiration",
        "strike",
        "right",
    )

    for field in required:
        if row.get(field) in (None, ""):
            raise ValueError(
                f"ThetaData staging row missing {field}: {row}"
            )

    return (
        run_id,
        str(row["provider"]),
        str(row["underlying"]).upper(),
        str(row["expiration"]),
        float(row["strike"]),
        str(row["right"]).upper(),
        row.get("bid"),
        row.get("ask"),
        row.get("bid_size"),
        row.get("ask_size"),
        row.get("bid_exchange"),
        row.get("ask_exchange"),
        row.get("bid_condition"),
        row.get("ask_condition"),
        row.get("open"),
        row.get("high"),
        row.get("low"),
        row.get("close"),
        row.get("volume"),
        row.get("count"),
        row.get("created"),
        row.get("last_trade"),
        json_dumps_stable(row),
    )


def json_dumps_stable(row: Mapping[str, Any]) -> str:
    import json
    return json.dumps(
        dict(row),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


INSERT_SQL = """
INSERT INTO thetadata_eod_option_rows(
    run_id,
    provider,
    underlying,
    expiration,
    strike,
    right,
    bid,
    ask,
    bid_size,
    ask_size,
    bid_exchange,
    ask_exchange,
    bid_condition,
    ask_condition,
    open,
    high,
    low,
    close,
    volume,
    count,
    provider_created,
    provider_last_trade,
    raw_json
)
VALUES (
    ?, ?, ?, ?, ?, ?,
    ?, ?, ?, ?, ?, ?, ?, ?,
    ?, ?, ?, ?, ?, ?,
    ?, ?, ?
)
"""


def insert_rows(
    connection: sqlite3.Connection,
    *,
    run_id: int,
    rows: Sequence[Mapping[str, Any]],
) -> int:
    payload = [
        flatten_for_insert(run_id, row)
        for row in rows
    ]

    connection.executemany(
        INSERT_SQL,
        payload,
    )

    return len(payload)


def complete_run(
    connection: sqlite3.Connection,
    *,
    run_id: int,
    completed_at_utc: str,
    row_count: int,
) -> None:
    connection.execute(
        """
        UPDATE thetadata_eod_runs
        SET
            completed_at_utc = ?,
            status = 'COMPLETED',
            row_count = ?,
            error_text = NULL
        WHERE run_id = ?
        """,
        (
            completed_at_utc,
            row_count,
            run_id,
        ),
    )


def fail_run(
    connection: sqlite3.Connection,
    *,
    run_id: int,
    completed_at_utc: str,
    error_text: str,
) -> None:
    connection.execute(
        """
        UPDATE thetadata_eod_runs
        SET
            completed_at_utc = ?,
            status = 'FAILED',
            error_text = ?
        WHERE run_id = ?
        """,
        (
            completed_at_utc,
            error_text,
            run_id,
        ),
    )
