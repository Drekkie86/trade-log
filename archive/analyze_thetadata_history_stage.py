from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path

from src.research.thetadata_empirical_diagnostics import (
    cross_underlying_daily_correlations,
    load_next_session_matches,
    load_spread_rows,
    summary,
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Empirical quote/spread/next-session diagnostics over the "
            "ThetaData staging DB."
        )
    )
    p.add_argument(
        "--db",
        default="thetadata_history_staging.db",
    )
    return p.parse_args()


def fmt(value):
    if value is None:
        return "NA"
    if isinstance(value, int):
        return str(value)
    return f"{value:.6f}"


def print_summary_block(title, values):
    s = summary(values)
    print(title)
    print("-" * len(title))
    for key in (
        "n",
        "mean",
        "median",
        "p10",
        "p25",
        "p75",
        "p90",
        "p95",
    ):
        print(f"{key:10s}: {fmt(s[key])}")
    print()


def main() -> int:
    args = parse_args()
    db = Path(args.db)

    if not db.exists():
        print(f"FAIL: staging DB not found: {db}")
        return 1

    spreads = load_spread_rows(db)
    matches = load_next_session_matches(db)

    print("Christiania - ThetaData empirical diagnostics v1")
    print("================================================")
    print("Historical EOD staging analysis only.")
    print("No edge claim. No canonical-data promotion.")
    print()

    print("DATASET")
    print(f"spread rows:             {len(spreads)}")
    print(f"next-session matches:    {len(matches)}")
    print()

    print_summary_block(
        "ABSOLUTE QUOTED SPREAD",
        [row.spread for row in spreads],
    )
    print_summary_block(
        "SPREAD / MID",
        [
            value
            for row in spreads
            if (value := row.spread_to_mid) is not None
        ],
    )
    print_summary_block(
        "HALF-SPREAD / MID",
        [
            value
            for row in spreads
            if (value := row.half_spread_to_mid) is not None
        ],
    )

    print("SPREAD / MID BY UNDERLYING")
    print("--------------------------")
    grouped_spreads = defaultdict(list)
    for row in spreads:
        value = row.spread_to_mid
        if value is not None:
            grouped_spreads[row.underlying].append(value)

    for symbol in sorted(grouped_spreads):
        s = summary(grouped_spreads[symbol])
        print(
            f"{symbol:6s} "
            f"n={s['n']:6d} "
            f"median={fmt(s['median'])} "
            f"p90={fmt(s['p90'])} "
            f"p95={fmt(s['p95'])}"
        )
    print()

    print_summary_block(
        "NEXT-OBSERVED-SESSION MID-TO-MID RETURN",
        [
            value
            for item in matches
            if (value := item.mid_to_mid_return) is not None
        ],
    )
    print_summary_block(
        "NEXT-OBSERVED-SESSION ASK-TO-BID RETURN",
        [
            value
            for item in matches
            if (value := item.ask_to_bid_return) is not None
        ],
    )
    print_summary_block(
        "QUOTED ROUND-TRIP DRAG",
        [
            value
            for item in matches
            if (value := item.quoted_round_trip_drag) is not None
        ],
    )

    zero_or_negative_exit_bid = sum(
        1 for item in matches if item.exit_bid <= 0
    )
    print("EXECUTION AVAILABILITY")
    print("----------------------")
    print(
        "matched rows with exit bid <= 0: "
        f"{zero_or_negative_exit_bid}"
    )
    print()

    print("CROSS-UNDERLYING DAILY CORRELATION")
    print("----------------------------------")
    print(
        "These are correlations of broad identical-contract daily mean "
        "returns, NOT Cohort 002 paired-edge correlations."
    )

    corr = cross_underlying_daily_correlations(
        matches,
        return_kind="mid_to_mid",
    )
    for (left, right), values in sorted(corr.items()):
        print(
            f"{left}-{right}: "
            f"n_days={values['n_days']} "
            f"pearson={fmt(values['pearson'])}"
        )

    print()
    print("INTERPRETATION GUARD")
    print("--------------------")
    print(
        "The next-session matcher uses consecutive completed dates present "
        "in staging; it is not yet exchange-calendar verified."
    )
    print(
        "These diagnostics describe EOD quotes. They do not establish "
        "intraday execution quality or an option-trading edge."
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
