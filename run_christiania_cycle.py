from __future__ import annotations

import argparse
import os
from collections import Counter
from pathlib import Path

from src.providers.massive import MassiveClient
from src.providers.thetadata import ThetaDataClient
from src.research.research_cycle import (
    run_research_cycle,
)


def load_env_file() -> None:
    path = Path(".env")
    if not path.exists():
        return

    for raw in path.read_text(
        encoding="utf-8"
    ).splitlines():
        line = raw.strip()

        if (
            not line
            or line.startswith("#")
            or "=" not in line
        ):
            continue

        name, value = line.split("=", 1)

        os.environ.setdefault(
            name.strip(),
            value.strip(),
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run one complete Christiania "
            "evidence-research cycle."
        )
    )

    parser.add_argument(
        "--symbols",
        nargs="+",
        default=[
            "AAPL",
            "JPM",
            "XOM",
        ],
    )

    parser.add_argument(
        "--min-dte",
        type=int,
        default=7,
    )

    parser.add_argument(
        "--max-dte",
        type=int,
        default=45,
    )

    parser.add_argument(
        "--max-spread-to-mid",
        type=float,
        default=0.20,
    )

    parser.add_argument(
        "--residual-threshold",
        type=float,
        default=0.03,
    )

    args = parser.parse_args()

    load_env_file()

    massive_key = os.environ.get(
        "MASSIVE_API_KEY"
    )

    if not massive_key:
        print(
            "REFUSED: MASSIVE_API_KEY is missing."
        )
        return 2

    print(
        "Christiania Research Cycle v1"
    )
    print(
        "=============================="
    )
    print(
        "Research evidence only."
    )
    print(
        "No shadow admission. No Saxo. No orders."
    )
    print()
    print(
        "Symbols: "
        + ", ".join(
            str(symbol).upper()
            for symbol in args.symbols
        )
    )
    print(
        f"DTE: {args.min_dte}-{args.max_dte}"
    )
    print(
        "Basic spread/mid ceiling: "
        f"{args.max_spread_to_mid:.2%}"
    )
    print(
        "Local IV residual threshold: "
        f"{args.residual_threshold:.4f}"
    )
    print()

    result = run_research_cycle(
        symbols=args.symbols,
        massive_client=
            MassiveClient(
                massive_key
            ),
        theta_client=
            ThetaDataClient(),
        min_dte=args.min_dte,
        max_dte=args.max_dte,
        max_spread_to_mid=
            args.max_spread_to_mid,
        residual_threshold=
            args.residual_threshold,
    )

    research = result.research
    structural = result.structural
    hypothesis = result.hypothesis

    print(
        f"Research run: {research.run_id}"
    )
    print(
        f"US session: "
        f"{research.us_session_date} "
        f"{research.us_session_state}"
    )
    print()

    print("Acquisition")
    for summary in research.summaries:
        print(
            "  "
            f"{summary.underlying}: "
            f"reference={summary.reference_contracts}, "
            f"quotes={summary.theta_quote_rows}, "
            f"greeks={summary.theta_greek_rows}, "
            f"unmatched={summary.theta_unmatched}"
        )

    print()
    print("Structural filter")
    print(
        f"  evaluated: "
        f"{structural.total_quotes}"
    )
    print(
        f"  eligible:  "
        f"{structural.eligible}"
    )
    print(
        f"  blocked:   "
        f"{structural.blocked}"
    )

    if structural.blocker_counts:
        print(
            "  blockers:"
        )
        for reason, count in sorted(
            structural.blocker_counts.items(),
            key=lambda item: (
                -item[1],
                item[0],
            ),
        ):
            print(
                f"    {reason}: {count}"
            )

    print()
    print("Hypothesis scanner")
    print(
        f"  scanner run: "
        f"{hypothesis.persisted_scanner_run_id}"
    )
    print(
        f"  structural input: "
        f"{hypothesis.structural_input_count}"
    )
    print(
        f"  evaluable:        "
        f"{hypothesis.evaluable_count}"
    )
    print(
        f"  surfaced:         "
        f"{hypothesis.surfaced_count}"
    )

    states = Counter(
        item.evaluation_state
        for item in hypothesis.evaluations
    )

    if states:
        print(
            "  states:"
        )
        for state, count in sorted(
            states.items()
        ):
            print(
                f"    {state}: {count}"
            )

    surfaced = sorted(
        (
            item
            for item in hypothesis.evaluations
            if item.evaluation_state
            == "SURFACED"
        ),
        key=lambda item:
            item.abs_iv_residual
            or 0.0,
        reverse=True,
    )

    if surfaced:
        print()
        print(
            "Top surfaced empirical anomalies"
        )
        for item in surfaced[:20]:
            print(
                "  "
                f"{item.underlying} "
                f"{item.expiration} "
                f"{item.right} "
                f"{item.strike:g} "
                f"{item.surfaced_direction} "
                f"residual="
                f"{item.iv_residual:+.4f}"
            )

    print()
    print(
        "Cycle complete."
    )
    print(
        "SURFACED remains an empirical anomaly, "
        "not a trade candidate or validated edge."
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
