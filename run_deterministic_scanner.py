from __future__ import annotations

import argparse

from src.database.repository import (
    get_connection,
)
from src.research.deterministic_scanner import (
    scan_research_run,
)


def latest_completed_run_id() -> int:
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT id
            FROM research_runs
            WHERE status = 'COMPLETED'
              AND cohort_id =
                  'INDEPENDENT_RESEARCH_RUNNER_V1'
            ORDER BY id DESC
            LIMIT 1;
            """
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        raise RuntimeError(
            "No completed independent research run found."
        )

    return int(row["id"])


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run Christiania's deterministic "
            "scanner against persisted evidence."
        )
    )

    parser.add_argument(
        "--run-id",
        type=int,
        default=None,
    )

    parser.add_argument(
        "--max-spread-to-mid",
        type=float,
        default=0.20,
    )

    args = parser.parse_args()

    run_id = (
        args.run_id
        if args.run_id is not None
        else latest_completed_run_id()
    )

    result = scan_research_run(
        research_run_id=run_id,
        max_spread_to_mid=
            args.max_spread_to_mid,
    )

    print(
        "Christiania Deterministic Scanner v1"
    )
    print(
        "===================================="
    )
    print(
        "Persisted-evidence evaluation only."
    )
    print(
        "No candidate creation. No orders."
    )
    print()
    print(
        f"Research run: {result.research_run_id}"
    )
    print(
        f"Scanner family: "
        f"{result.scanner_family_id}"
    )
    print(
        f"Scanner version: "
        f"{result.scanner_version}"
    )
    print(
        f"Rule version: "
        f"{result.rule_version}"
    )
    print()
    print(
        f"Quotes evaluated: "
        f"{result.total_quotes}"
    )
    print(
        f"Structurally eligible: "
        f"{result.eligible}"
    )
    print(
        f"Blocked: "
        f"{result.blocked}"
    )

    if result.blocker_counts:
        print()
        print("Blocking reasons")
        for reason, count in sorted(
            result.blocker_counts.items(),
            key=lambda item: (
                -item[1],
                item[0],
            ),
        ):
            print(
                f"  {reason}: {count}"
            )

    eligible = [
        item
        for item in result.observations
        if item.structurally_eligible
    ]

    if eligible:
        print()
        print(
            "First structurally eligible observations"
        )
        for item in eligible[:20]:
            print(
                "  "
                f"{item.underlying} "
                f"{item.expiration} "
                f"{item.right} "
                f"{item.strike:g} "
                f"spread/mid="
                f"{item.spread_to_mid:.4f} "
                f"age="
                f"{item.quote_age_seconds:.2f}s "
                f"delta="
                f"{item.delta:.4f}"
            )

    print()
    print(
        "IMPORTANT: structurally eligible "
        "does not mean candidate or edge."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
