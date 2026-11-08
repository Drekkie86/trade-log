from __future__ import annotations

import argparse
import sqlite3


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--db",
        default="thetadata_history_staging.db",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()

    with sqlite3.connect(args.db) as connection:
        runs = connection.execute(
            """
            SELECT
                symbol,
                trading_date,
                requested_max_dte,
                status,
                row_count,
                error_text
            FROM thetadata_eod_runs
            ORDER BY trading_date, symbol
            """
        ).fetchall()

        totals = connection.execute(
            """
            SELECT
                COUNT(*),
                COUNT(DISTINCT underlying),
                COUNT(DISTINCT expiration),
                SUM(
                    CASE
                    WHEN bid IS NOT NULL AND ask IS NOT NULL
                    THEN 1 ELSE 0 END
                ),
                AVG(
                    CASE
                    WHEN bid IS NOT NULL
                     AND ask IS NOT NULL
                     AND ask >= bid
                    THEN ask - bid
                    END
                )
            FROM thetadata_eod_option_rows
            """
        ).fetchone()

    print("Christiania - ThetaData staging inspection")
    print("=========================================")
    print()
    print("RUNS")
    for row in runs:
        print(row)

    print()
    print("TOTALS")
    labels = (
        "rows",
        "underlyings",
        "expirations",
        "two_sided_rows",
        "mean_raw_spread",
    )
    for label, value in zip(labels, totals):
        print(f"{label:20s}: {value}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
