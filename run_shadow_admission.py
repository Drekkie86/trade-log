from __future__ import annotations

import argparse
from collections import Counter

from src.providers.ecb_fx import (
    fetch_ecb_eurusd,
)
from src.research.shadow_admission import (
    admit_shadow_proposals,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Apply deterministic research-only shadow "
            "admission to pending defined-risk proposals."
        )
    )

    parser.add_argument(
        "--proposal-id",
        type=int,
        action="append",
        dest="proposal_ids",
        default=None,
    )

    args = parser.parse_args()

    print(
        "Christiania Shadow Admission v1"
    )
    print(
        "==============================="
    )
    print(
        "Research-only admission."
    )
    print(
        "No Saxo order. No live-edge validation."
    )
    print()

    fx = fetch_ecb_eurusd()

    print(
        "FX evidence:"
    )
    print(
        f"  ECB {fx.reference_date}: "
        f"1 EUR = {fx.rate:.6f} USD"
    )
    print()

    result = admit_shadow_proposals(
        fx=fx,
        proposal_ids=args.proposal_ids,
    )

    print(
        f"Proposals evaluated: "
        f"{result.proposal_count}"
    )
    print(
        f"Admitted:            "
        f"{result.admitted_count}"
    )
    print(
        f"Blocked:             "
        f"{result.blocked_count}"
    )

    reasons = Counter(
        item.reason_code
        for item in result.decisions
    )

    if reasons:
        print()
        print("Decisions")
        for reason, count in (
            reasons.most_common()
        ):
            print(
                f"  {reason}: {count}"
            )

    for item in result.decisions:
        print()
        print(
            f"Proposal {item.proposal_id}: "
            f"{item.decision}"
        )
        print(
            "  theoretical max loss: "
            f"EUR "
            f"{item.converted_max_loss_eur_minor / 100:.2f}"
        )
        print(
            "  estimated round-trip cost reserve: "
            f"EUR "
            f"{item.estimated_cost_eur_minor / 100:.2f}"
        )
        print(
            "  total reserved risk: "
            f"EUR "
            f"{item.reserved_risk_eur_minor / 100:.2f}"
        )
        print(
            "  bankroll cap: "
            f"EUR "
            f"{item.bankroll_cap_eur_minor / 100:.2f}"
        )

        if item.candidate_id is not None:
            print(
                f"  shadow candidate: "
                f"{item.candidate_id}"
            )

    print()
    print(
        "ADMITTED means shadow-research tracking only."
    )
    print(
        "It does not authorize or recommend a live trade."
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
