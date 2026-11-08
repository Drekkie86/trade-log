from __future__ import annotations

import argparse
import sqlite3
import tempfile
import time
from pathlib import Path

from src.database.repository import (
    create_listing_reference_contract,
    create_listing_reference_contracts,
    get_connection,
)

ROOT = Path(__file__).resolve().parent


def initialize_database(path: Path) -> int:
    conn = get_connection(path)
    try:
        conn.executescript(
            (ROOT / "trade_log_schema.sql").read_text(
                encoding="utf-8"
            )
        )
        for migration in (
            "007_selection_universe_integrity.sql",
            "008_shadow_persistence.sql",
            "009_hostile_review_hardening.sql",
        ):
            conn.executescript(
                (ROOT / "migrations" / migration).read_text(
                    encoding="utf-8"
                )
            )

        cursor = conn.execute(
            """
            INSERT INTO research_runs (
                cohort_id,
                started_at,
                code_git_sha,
                preregistration_hash,
                us_session_date,
                us_session_state,
                status
            )
            VALUES (
                'BENCHMARK',
                '2026-08-31T18:00:00Z',
                'benchmark',
                'benchmark',
                '2026-08-31',
                'INTRADAY',
                'STARTED'
            );
            """
        )
        conn.commit()
        return int(cursor.lastrowid)
    finally:
        conn.close()


def rows(run_id: int, count: int):
    return [
        {
            "research_run_id": run_id,
            "provider": "MASSIVE",
            "underlying": "AAPL",
            "provider_contract_id": f"O:BENCH{i:08d}",
            "option_symbol": f"O:BENCH{i:08d}",
            "expiration": "2026-09-18",
            "strike": 100.0 + (i / 1000.0),
            "right": "C" if i % 2 == 0 else "P",
            "observed_at": "2026-08-31T18:00:00Z",
        }
        for i in range(count)
    ]


def run_single(count: int) -> float:
    with tempfile.TemporaryDirectory() as temp:
        db = Path(temp) / "single.db"
        run_id = initialize_database(db)
        payload = rows(run_id, count)

        started = time.perf_counter()
        for item in payload:
            create_listing_reference_contract(
                item,
                db_path=db,
            )
        return time.perf_counter() - started


def run_batch(count: int) -> float:
    with tempfile.TemporaryDirectory() as temp:
        db = Path(temp) / "batch.db"
        run_id = initialize_database(db)
        payload = rows(run_id, count)

        started = time.perf_counter()
        create_listing_reference_contracts(
            payload,
            db_path=db,
        )
        return time.perf_counter() - started


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--rows",
        type=int,
        default=10_000,
    )
    args = parser.parse_args()

    count = args.rows
    print("Christiania persistence benchmark")
    print("===============================")
    print(f"Rows: {count:,}")
    print()

    single = run_single(count)
    batch = run_batch(count)
    speedup = single / batch if batch else float("inf")

    print(f"Single-row path: {single:.3f} s")
    print(f"Batch path:      {batch:.3f} s")
    print(f"Speedup:         {speedup:.2f}x")
    print()
    print(
        "This benchmark compares the retained compatibility "
        "single-row API against the new executemany batch path "
        "using equivalent temporary v9 databases."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
