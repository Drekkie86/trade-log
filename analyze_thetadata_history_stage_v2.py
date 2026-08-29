from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from pathlib import Path

from src.research.thetadata_empirical_diagnostics import (
    load_next_session_matches,
    load_spread_rows,
    summary,
)
from src.research.thetadata_empirical_diagnostics_v2 import (
    cross_underlying_robust_correlations,
    dte,
    dte_bucket,
    matched_entry_spread_to_mid,
    matched_quote_state,
    premium_bucket,
    quote_state,
    spread_bucket,
)


def fmt(value):
    if value is None:
        return "NA"
    if isinstance(value, int):
        return str(value)
    return f"{value:.6f}"


def print_dist(label, values):
    s = summary(values)
    print(label)
    print("-" * len(label))
    for key in ("n", "mean", "median", "p10", "p25", "p75", "p90", "p95"):
        print(f"{key:10s}: {fmt(s[key])}")
    print()


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--db", default="thetadata_history_staging.db")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    db = Path(args.db)
    if not db.exists():
        print(f"FAIL: {db} not found")
        return 1

    spreads = load_spread_rows(db)
    matches = load_next_session_matches(db)

    print("Christiania - ThetaData empirical diagnostics v2")
    print("================================================")
    print("DESCRIPTIVE ONLY — NO EDGE CLAIM")
    print()

    quote_states = Counter(quote_state(row) for row in spreads)
    print("QUOTE-STATE PREVALENCE")
    print("----------------------")
    for state, count in sorted(quote_states.items()):
        print(
            f"{state:24s}: {count:6d} "
            f"({count / len(spreads):.3%})"
        )
    print()

    positive_two_sided = [
        row for row in spreads if row.bid > 0 and row.ask > 0
    ]

    print_dist(
        "SPREAD / MID — ALL OBSERVATIONS",
        [row.spread_to_mid for row in spreads if row.spread_to_mid is not None],
    )
    print_dist(
        "SPREAD / MID — POSITIVE BID+ASK ONLY",
        [
            row.spread_to_mid
            for row in positive_two_sided
            if row.spread_to_mid is not None
        ],
    )

    print("SPREAD/MID BUCKETS — ALL OBSERVATIONS")
    print("-------------------------------------")
    spread_counts = Counter(
        spread_bucket(row.spread_to_mid) for row in spreads
    )
    for bucket, count in sorted(spread_counts.items()):
        print(
            f"{bucket:12s}: {count:6d} "
            f"({count / len(spreads):.3%})"
        )
    print()

    print("ENTRY PREMIUM BUCKETS — NEXT-SESSION MATCHES")
    print("--------------------------------------------")
    premium_counts = Counter(
        premium_bucket(item.entry_ask) for item in matches
    )
    for bucket, count in sorted(premium_counts.items()):
        print(
            f"{bucket:12s}: {count:6d} "
            f"({count / len(matches):.3%})"
        )
    print()

    print("MATCHED QUOTE STATES")
    print("--------------------")
    matched_states = Counter(matched_quote_state(item) for item in matches)
    for state, count in sorted(matched_states.items()):
        print(
            f"{state:24s}: {count:6d} "
            f"({count / len(matches):.3%})"
        )
    print()

    all_exec = [
        item.ask_to_bid_return
        for item in matches
        if item.ask_to_bid_return is not None
    ]
    positive_bid_exec = [
        item.ask_to_bid_return
        for item in matches
        if (
            item.ask_to_bid_return is not None
            and item.entry_bid > 0
            and item.exit_bid > 0
        )
    ]
    tight_exec = [
        item.ask_to_bid_return
        for item in matches
        if (
            item.ask_to_bid_return is not None
            and item.entry_bid > 0
            and item.exit_bid > 0
            and (
                (s := matched_entry_spread_to_mid(item))
                is not None
                and s <= 0.25
            )
        )
    ]

    print_dist(
        "ASK-TO-BID RETURN — ALL MATCHED",
        all_exec,
    )
    print_dist(
        "ASK-TO-BID RETURN — POSITIVE BIDS BOTH DAYS",
        positive_bid_exec,
    )
    print_dist(
        "ASK-TO-BID RETURN — POSITIVE BIDS + ENTRY SPREAD/MID <=25%",
        tight_exec,
    )

    print("ASK-TO-BID MEDIAN BY ENTRY ASK BUCKET")
    print("-------------------------------------")
    grouped = defaultdict(list)
    for item in matches:
        value = item.ask_to_bid_return
        if value is not None:
            grouped[premium_bucket(item.entry_ask)].append(value)
    for bucket, values in sorted(grouped.items()):
        s = summary(values)
        print(
            f"{bucket:12s} n={s['n']:6d} "
            f"median={fmt(s['median'])} "
            f"p25={fmt(s['p25'])} "
            f"p75={fmt(s['p75'])}"
        )
    print()

    print("ASK-TO-BID MEDIAN BY DTE BUCKET")
    print("-------------------------------")
    grouped_dte = defaultdict(list)
    for item in matches:
        value = item.ask_to_bid_return
        if value is None:
            continue
        grouped_dte[
            dte_bucket(dte(item.entry_date, item.expiration))
        ].append(value)
    for bucket, values in sorted(grouped_dte.items()):
        s = summary(values)
        print(
            f"{bucket:8s} n={s['n']:6d} "
            f"median={fmt(s['median'])} "
            f"p25={fmt(s['p25'])} "
            f"p75={fmt(s['p75'])}"
        )
    print()

    print("ROBUST CROSS-UNDERLYING CORRELATION")
    print("-----------------------------------")
    print("Daily statistic = MEDIAN identical-contract MID-TO-MID return.")
    print("This is still NOT Cohort 002 paired-edge correlation.")
    for label, kwargs in (
        ("ALL", {}),
        (
            "POSITIVE_BIDS",
            {"require_positive_bids": True},
        ),
        (
            "POSITIVE_BIDS_AND_ENTRY_SPREAD<=25%",
            {
                "require_positive_bids": True,
                "max_entry_spread_to_mid": 0.25,
            },
        ),
    ):
        print(label)
        corr = cross_underlying_robust_correlations(
            matches,
            statistic="median",
            **kwargs,
        )
        for (left, right), cell in sorted(corr.items()):
            print(
                f"  {left}-{right}: "
                f"n_days={cell['n_days']} "
                f"pearson={fmt(cell['pearson'])}"
            )
    print()

    print("INTERPRETATION GUARD")
    print("--------------------")
    print(
        "Zero-bid and wide-spread contracts are retained in the measurement "
        "population. The stratified views do not delete them; they expose how "
        "much they drive aggregate statistics."
    )
    print(
        "No result from this script may be promoted to an empirical edge or "
        "Cohort 002 paired-edge parameter."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
