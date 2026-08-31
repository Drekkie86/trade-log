from __future__ import annotations

import argparse
from collections import Counter

from src.database.repository import get_connection
from src.research.shadow_structure_bridge import (
    build_shadow_structure_proposals,
)


def latest_hypothesis_scanner_run_id() -> int:
    conn = get_connection()

    try:
        row = conn.execute(
            """
            SELECT id
            FROM hypothesis_scanner_runs
            ORDER BY id DESC
            LIMIT 1;
            """
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        raise RuntimeError(
            "No hypothesis scanner run exists."
        )

    return int(row["id"])


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build bounded-loss shadow structure "
            "proposals from surfaced hypothesis evidence."
        )
    )

    parser.add_argument(
        "--scanner-run-id",
        type=int,
        default=None,
    )

    parser.add_argument(
        "--no-persist",
        action="store_true",
    )

    args = parser.parse_args()

    scanner_run_id = (
        args.scanner_run_id
        if args.scanner_run_id is not None
        else latest_hypothesis_scanner_run_id()
    )

    result = build_shadow_structure_proposals(
        hypothesis_scanner_run_id=
            scanner_run_id,
        persist=
            not args.no_persist,
    )

    print(
        "Christiania Shadow Structure Bridge v1"
    )
    print(
        "======================================"
    )
    print(
        "Defined-risk proposal construction only."
    )
    print(
        "No shadow admission. No orders."
    )
    print()
    print(
        f"Hypothesis scanner run: "
        f"{result.hypothesis_scanner_run_id}"
    )
    print(
        f"Surfaced anomalies:      "
        f"{result.surfaced_count}"
    )
    print(
        f"Structures proposed:     "
        f"{result.proposed_count}"
    )
    print(
        f"Blocked:                 "
        f"{result.blocked_count}"
    )

    reasons = Counter(
        item.reason_code
        for item in result.proposals
    )

    if reasons:
        print()
        print("Reasons")
        for reason, count in reasons.most_common():
            print(
                f"  {reason}: {count}"
            )

    proposed = [
        item
        for item in result.proposals
        if item.proposal_state
        == "PROPOSED"
    ]

    if proposed:
        print()
        print(
            "Defined-risk proposals"
        )

        for item in proposed[:20]:
            max_loss = (
                item.max_theoretical_loss_minor
                / 100.0
                if item.max_theoretical_loss_minor
                is not None
                else None
            )

            print(
                "  "
                f"{item.underlying} "
                f"{item.expiration} "
                f"{item.right} "
                f"{item.target_strike:g} "
                f"{item.anomaly_direction} "
                f"{item.structure_id} "
                f"max_loss="
                f"{item.risk_currency} "
                f"{max_loss:.2f}"
            )

    print()
    print(
        "IMPORTANT: PROPOSED is not ADMITTED."
    )
    print(
        "No proposal becomes a shadow candidate "
        "until EUR bankroll sizing, FX, costs, and "
        "governance checks are satisfied."
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
