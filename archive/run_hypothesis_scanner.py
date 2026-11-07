from __future__ import annotations

import argparse
from collections import Counter

from src.database.repository import get_connection
from src.research.hypothesis_scanner import (
    scan_local_iv_residuals,
)


def latest_completed_run() -> int:
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
            "Run Christiania's first deterministic "
            "hypothesis scanner."
        )
    )

    parser.add_argument(
        "--run-id",
        type=int,
        default=None,
    )

    parser.add_argument(
        "--residual-threshold",
        type=float,
        default=0.03,
    )

    parser.add_argument(
        "--no-persist",
        action="store_true",
    )

    args = parser.parse_args()

    run_id = (
        args.run_id
        if args.run_id is not None
        else latest_completed_run()
    )

    result = scan_local_iv_residuals(
        research_run_id=run_id,
        residual_threshold=
            args.residual_threshold,
        persist=
            not args.no_persist,
    )

    print(
        "Christiania Hypothesis Scanner v1"
    )
    print(
        "================================="
    )
    print(
        "Local IV residual anomaly detector."
    )
    print(
        "No trades. No edge claim."
    )
    print()
    print(
        f"Research run: {result.research_run_id}"
    )
    print(
        f"Scanner run: "
        f"{result.persisted_scanner_run_id}"
    )
    print(
        f"Family: {result.scanner_family_id}"
    )
    print(
        f"Rules:  {result.rule_version}"
    )
    print()
    print(
        f"Structural input: "
        f"{result.structural_input_count}"
    )
    print(
        f"Evaluable:        "
        f"{result.evaluable_count}"
    )
    print(
        f"Surfaced:         "
        f"{result.surfaced_count}"
    )

    states = Counter(
        item.evaluation_state
        for item in result.evaluations
    )

    reasons = Counter(
        item.reason_code
        for item in result.evaluations
    )

    if states:
        print()
        print("Evaluation states")
        for state, count in states.items():
            print(
                f"  {state}: {count}"
            )

    if reasons:
        print()
        print("Reasons")
        for reason, count in reasons.most_common():
            print(
                f"  {reason}: {count}"
            )

    surfaced = [
        item
        for item in result.evaluations
        if item.evaluation_state
        == "SURFACED"
    ]

    if surfaced:
        print()
        print(
            "Surfaced empirical anomalies"
        )

        ranked = sorted(
            surfaced,
            key=lambda item:
                item.abs_iv_residual
                or 0.0,
            reverse=True,
        )

        for item in ranked[:20]:
            print(
                "  "
                f"{item.underlying} "
                f"{item.expiration} "
                f"{item.right} "
                f"{item.strike:g} "
                f"{item.surfaced_direction} "
                f"residual="
                f"{item.iv_residual:+.4f} "
                f"IV={item.implied_volatility:.4f}"
            )

    print()
    print(
        "SURFACED means empirical local-IV anomaly only."
    )
    print(
        "It is not a trade candidate and not validated edge."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
