from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import time

from src.providers.thetadata import (
    ThetaDataClient,
    ThetaDataError,
)
from src.research.thetadata_history_staging import (
    complete_run,
    create_run,
    fail_run,
    initialize_staging_db,
    insert_rows,
    reset_failed_run,
)


DEFAULT_DB = "thetadata_history_staging.db"


def utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Import ThetaData historical option EOD responses into a "
            "separate Christiania staging database."
        )
    )
    p.add_argument(
        "symbol",
        help="Underlying symbol, e.g. AAPL",
    )
    p.add_argument(
        "start_date",
        help="YYYY-MM-DD",
    )
    p.add_argument(
        "end_date",
        help="YYYY-MM-DD",
    )
    p.add_argument(
        "--max-dte",
        type=int,
        default=45,
    )
    p.add_argument(
        "--db",
        default=DEFAULT_DB,
    )
    p.add_argument(
        "--sleep-seconds",
        type=float,
        default=3.2,
        help=(
            "Pause between requests. Default 3.2s stays below the "
            "free-tier 20 requests/minute limit."
        ),
    )
    p.add_argument(
        "--include-weekends",
        action="store_true",
        help="Normally weekends are skipped.",
    )
    p.add_argument(
        "--retry-failed",
        action="store_true",
        help="Explicitly retry FAILED or abandoned RUNNING runs. COMPLETED runs are never overwritten.",
    )
    return p.parse_args()


def iter_dates(
    start: date,
    end: date,
    *,
    include_weekends: bool,
):
    current = start
    while current <= end:
        if include_weekends or current.weekday() < 5:
            yield current
        current += timedelta(days=1)


def main() -> int:
    args = parse_args()

    symbol = args.symbol.upper()
    start = date.fromisoformat(args.start_date)
    end = date.fromisoformat(args.end_date)

    if end < start:
        print("FAIL: end_date is before start_date.")
        return 2

    db_path = Path(args.db)
    initialize_staging_db(db_path)

    client = ThetaDataClient()

    print("Christiania - ThetaData historical staging import")
    print("================================================")
    print("Separate staging DB only. trade_log.db is untouched.")
    print(f"Symbol: {symbol}")
    print(f"Range:  {start} -> {end}")
    print(f"DB:     {db_path.resolve()}")
    print()

    overall_fail = False

    dates = list(
        iter_dates(
            start,
            end,
            include_weekends=args.include_weekends,
        )
    )

    for index, trading_date in enumerate(dates, start=1):
        print(
            f"[{index}/{len(dates)}] "
            f"{symbol} {trading_date}"
        )

        with sqlite3.connect(db_path) as connection:
            existing = connection.execute(
                """
                SELECT run_id, status, row_count
                FROM thetadata_eod_runs
                WHERE symbol = ?
                  AND trading_date = ?
                  AND requested_max_dte = ?
                """,
                (symbol, trading_date.isoformat(), args.max_dte),
            ).fetchone()

            if existing is not None and existing[1] == "COMPLETED":
                print(f"  SKIP completed run: rows={existing[2]}")
                continue

            if existing is not None:
                if not args.retry_failed:
                    print(
                        f"  BLOCKED existing {existing[1]} run_id={existing[0]}. "
                        "Use --retry-failed only after reviewing the failure."
                    )
                    overall_fail = True
                    continue
                run_id = int(existing[0])
                reset_failed_run(
                    connection,
                    run_id=run_id,
                    started_at_utc=utc_now(),
                )
            else:
                run_id = create_run(
                    connection,
                    symbol=symbol,
                    trading_date=trading_date,
                    max_dte=args.max_dte,
                    started_at_utc=utc_now(),
                )
            connection.commit()

        try:
            rows = client.option_eod_chain_flat(
                symbol,
                trading_date,
                max_dte=args.max_dte,
            )

            with sqlite3.connect(db_path) as connection:
                connection.execute("BEGIN")
                inserted = insert_rows(
                    connection,
                    run_id=run_id,
                    rows=rows,
                )
                complete_run(
                    connection,
                    run_id=run_id,
                    completed_at_utc=utc_now(),
                    row_count=inserted,
                )
                connection.commit()

            print(f"  COMPLETED rows={inserted}")

        except Exception as exc:
            overall_fail = True

            with sqlite3.connect(db_path) as connection:
                fail_run(
                    connection,
                    run_id=run_id,
                    completed_at_utc=utc_now(),
                    error_text=str(exc),
                )
                connection.commit()

            print(f"  FAILED: {exc}")

        if index < len(dates):
            time.sleep(max(0.0, args.sleep_seconds))

    print()
    if overall_fail:
        print("IMPORT FINISHED WITH FAILURES")
        return 1

    print("IMPORT COMPLETED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
