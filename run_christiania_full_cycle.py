from __future__ import annotations

import argparse
import os
from collections import Counter
from pathlib import Path

from src.providers.massive import MassiveClient
from src.providers.thetadata import ThetaDataClient
from src.research.full_research_cycle import (
    run_full_research_cycle,
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

        name, value = line.split(
            "=",
            1,
        )

        os.environ.setdefault(
            name.strip(),
            value.strip(),
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run Christiania's full autonomous "
            "research-only cycle."
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
        "Christiania Full Research Cycle v1"
    )
    print(
        "=================================="
    )
    print(
        "Autonomous research-only pipeline."
    )
    print(
        "No Saxo order. No live-edge validation."
    )
    print()

    result = run_full_research_cycle(
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

    cycle = result.research_cycle
    research = cycle.research
    structural = cycle.structural
    hypothesis = cycle.hypothesis
    bridge = result.structure_bridge

    print(
        f"Research run: "
        f"{research.run_id}"
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

    print()
    print("Structure bridge")
    print(
        f"  surfaced: "
        f"{bridge.surfaced_count}"
    )
    print(
        f"  proposed: "
        f"{bridge.proposed_count}"
    )
    print(
        f"  blocked:  "
        f"{bridge.blocked_count}"
    )

    if bridge.proposals:
        reasons = Counter(
            item.reason_code
            for item in bridge.proposals
        )

        for reason, count in (
            reasons.most_common()
        ):
            print(
                f"    {reason}: {count}"
            )

    print()
    print("Shadow admission")

    if result.admission is None:
        print(
            "  skipped: no PROPOSED structures"
        )
    else:
        admission = result.admission

        if result.fx_observation is not None:
            fx = result.fx_observation
            print(
                f"  ECB {fx.reference_date}: "
                f"1 EUR = {fx.rate:.6f} USD"
            )

        print(
            f"  evaluated: "
            f"{admission.proposal_count}"
        )
        print(
            f"  admitted:  "
            f"{admission.admitted_count}"
        )
        print(
            f"  blocked:   "
            f"{admission.blocked_count}"
        )

        for item in admission.decisions:
            print(
                "    "
                f"proposal={item.proposal_id} "
                f"{item.decision} "
                f"reserve="
                f"EUR "
                f"{item.reserved_risk_eur_minor / 100:.2f} "
                f"reason={item.reason_code}"
            )

            if item.candidate_id is not None:
                print(
                    "      "
                    f"shadow_candidate_id="
                    f"{item.candidate_id}"
                )

    print()
    print(
        "Full cycle complete."
    )
    print(
        "Any admitted object is shadow research only."
    )
    print(
        "No live broker order has been created."
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
