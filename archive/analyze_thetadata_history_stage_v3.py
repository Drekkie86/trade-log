"""
Christiania — re-run empirical diagnostics with the N2/N3/N4 fixes applied.

Read-only against the existing ThetaData staging database. Writes
nothing. Produces the corrected numbers side by side with what they
replace, so the delta is visible rather than the old numbers just
disappearing.

Usage:

    python analyze_thetadata_history_stage_v3.py [path-to-staging-db]

Defaults to thetadata_history_staging.db in the current directory, same
as v1 and v2.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.research.thetadata_empirical_diagnostics_v3 import (  # noqa: E402
    classify_unmatched_entries,
    count_eligible_entry_rows,
    dependence_report,
    group_medians,
    load_matched_pairs_v3,
    moneyness_band,
    partition_pairs,
    quantile,
    synthetic_forwards,
    zero_move_fraction,
)


def summarize(label: str, values: list[float]) -> None:
    print(f"{label}")
    print("-" * len(label))
    if not values:
        print("n : 0 (no observations)")
        print()
        return
    print(f"n      : {len(values)}")
    print(f"median : {quantile(values, 0.5):.6f}")
    print(f"p25    : {quantile(values, 0.25):.6f}")
    print(f"p75    : {quantile(values, 0.75):.6f}")
    print()


def main() -> int:
    db_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
        "thetadata_history_staging.db"
    )

    if not db_path.exists():
        print(f"FAIL: staging database not found at {db_path}")
        return 1

    print("Christiania - ThetaData empirical diagnostics v3")
    print("=================================================")
    print("DESCRIPTIVE ONLY - NO EDGE CLAIM")
    print(f"Database: {db_path}")
    print()

    print("Loading matched pairs and computing forwards ...")
    pairs = load_matched_pairs_v3(db_path)
    unmatched = classify_unmatched_entries(db_path)
    eligible_entries = count_eligible_entry_rows(db_path)
    accounted_entries = len(pairs) + len(unmatched)
    if accounted_entries != eligible_entries:
        raise RuntimeError(
            "ACCOUNTING INVARIANT FAILED: eligible entry rows "
            f"({eligible_entries}) != matched ({len(pairs)}) + unmatched "
            f"({len(unmatched)}) = {accounted_entries}. A provider row may "
            "have a partial/invalid next-session quote that is disappearing "
            "from both populations. Do not interpret diagnostics until fixed."
        )
    forwards = synthetic_forwards(db_path)
    print(f"Eligible entry rows      : {eligible_entries}")
    print(f"Matched pairs (all)      : {len(pairs)}")
    print(f"Unmatched entry rows     : {len(unmatched)}")
    print("Accounting invariant     : PASS")
    print(f"Parity references computed: {len(forwards)}")
    print()

    # -------------------------------------------------------------
    # N2: separate one-session from held-to-expiry
    # -------------------------------------------------------------
    all_nonexpiry = partition_pairs(pairs, calendar_days=None)
    split = partition_pairs(pairs, calendar_days=1)

    print("ESTIMAND SEPARATION (fixes N2/B3)")
    print("==================================")
    print(f"NEXT_OBSERVED_SESSION_NONEXPIRY : {len(all_nonexpiry['ONE_SESSION'])}")
    print(f"ONE_CALENDAR_DAY_NONEXPIRY      : {len(split['ONE_SESSION'])}")
    print(f"HELD_TO_EXPIRY                  : {len(split['HELD_TO_EXPIRY'])}")
    print(f"NONEXPIRY_MULTI_CALENDAR_DAY    : {len(split['EXCLUDED_BY_SPAN'])}")
    print()
    spans={}
    for pair in all_nonexpiry['ONE_SESSION']:
        spans[pair.calendar_days_elapsed]=spans.get(pair.calendar_days_elapsed,0)+1
    print("Calendar-day spans among non-expiry next-observed-session pairs:")
    for days,count in sorted(spans.items()):
        print(f"  {days} day(s): {count}")
    print()

    one_session = [
        p.ask_to_bid_return
        for p in split["ONE_SESSION"]
        if p.ask_to_bid_return is not None
    ]
    expiry = [
        p.ask_to_bid_return
        for p in split["HELD_TO_EXPIRY"]
        if p.ask_to_bid_return is not None
    ]

    summarize(
        "ASK-TO-BID RETURN - ONE_SESSION ONLY (previously pooled with expiry)",
        one_session,
    )
    summarize(
        "ASK-TO-BID RETURN - HELD_TO_EXPIRY ONLY (a different question)",
        expiry,
    )

    quoted_crossing = [
        p.entry_quoted_crossing_fraction_of_ask
        for p in split["ONE_SESSION"]
        if p.entry_quoted_crossing_fraction_of_ask is not None
    ]
    summarize(
        "SAME-OBSERVATION QUOTED CROSSING / ASK - ONE-CALENDAR-DAY POPULATION",
        quoted_crossing,
    )
    print("This is the displayed bid/ask crossing penalty, not actual slippage.")
    print()

    print("UNMATCHED / CENSORING ACCOUNTING")
    print("================================")
    expiry_missing=[u for u in unmatched if u.mechanism=="EXPIRY_RELATED"]
    nonexpiry_missing=[u for u in unmatched if u.mechanism=="MISSING_NEXT_QUOTE_NONEXPIRY"]
    print(f"EXPIRY_RELATED                 : {len(expiry_missing)}")
    print(f"MISSING_NEXT_QUOTE_NONEXPIRY   : {len(nonexpiry_missing)}")
    complete_case=list(one_session)
    worst_case=complete_case + [
        -1.0 for u in nonexpiry_missing if u.entry_ask > 0
    ]
    summarize("ONE-DAY NONEXPIRY COMPLETE-CASE ASK-TO-BID", complete_case)
    summarize("ONE-DAY NONEXPIRY + NONEXPIRY-MISSING WORST CASE", worst_case)

    # -------------------------------------------------------------
    # N3: moneyness stratification via parity-derived reference
    # -------------------------------------------------------------
    print("MONEYNESS STRATIFICATION (fixes N3)")
    print("=====================================")
    print("Approximate parity reference per (underlying, session, expiration).")
    print("No external underlying/rate/dividend source is used, so treat this as")
    print("a coarse moneyness stratifier, not an exact forward-price estimate.")
    print()

    labelled: list[tuple[str, float]] = []
    for pair in split["ONE_SESSION"]:
        key = (pair.underlying, pair.entry_date, pair.expiration)
        forward = forwards.get(key)
        if forward is None:
            continue
        band = moneyness_band(pair.strike, forward.forward, pair.right)
        if band is None or pair.ask_to_bid_return is None:
            continue
        labelled.append((band, pair.ask_to_bid_return))

    by_band = group_medians(labelled)
    print(f"{'band':16} {'n':>6} {'median':>10} {'p25':>10} {'p75':>10}")
    for band, stats in by_band.items():
        print(
            f"{band:16} {stats['n']:6d} "
            f"{stats['median']:10.4f} {stats['p25']:10.4f} "
            f"{stats['p75']:10.4f}"
        )
    print()
    print("EXTREME_ITM/EXTREME_OTM were previously pooled into the same")
    print("percentile as NEAR_ATM. Compare this table against the")
    print("'ASK-TO-BID MEDIAN BY ENTRY ASK BUCKET' table in v2 output.")
    print()

    # -------------------------------------------------------------
    # N4: dependence, both estimators, both with intervals
    # -------------------------------------------------------------
    print("CROSS-UNDERLYING DEPENDENCE (fixes N4)")
    print("=========================================")
    fraction = zero_move_fraction(all_nonexpiry["ONE_SESSION"])
    if fraction is not None:
        print(
            f"Share of ONE_SESSION pairs with an unchanged mid: "
            f"{fraction:.1%}"
        )
        if fraction > 0.5:
            print(
                "WARNING: above 50%. A daily cross-sectional MEDIAN return "
                "is pinned near zero and cannot carry market information. "
                "Prefer the mean estimator, or a delta-banded subpopulation."
            )
    print()

    for estimate in dependence_report(all_nonexpiry["ONE_SESSION"]):
        left, right = estimate.pair
        if estimate.r is None:
            print(f"{left}-{right} [{estimate.statistic}] : insufficient data")
            continue
        interval = (
            f"[{estimate.ci_low:+.3f}, {estimate.ci_high:+.3f}]"
            if estimate.ci_low is not None
            else "[unavailable]"
        )
        flag = " *excludes zero*" if estimate.excludes_zero else ""
        print(
            f"{left}-{right} [{estimate.statistic:>6}] "
            f"n_days={estimate.n_days:3d} r={estimate.r:+.3f} "
            f"CI={interval}{flag}"
        )
    print()
    print("Neither estimator is selected here. Both are reported so the")
    print("reader can see whether they disagree, and by how much, before")
    print("any downstream effective-N calculation uses either one.")
    print()

    print("INTERPRETATION GUARD")
    print("---------------------")
    print("These diagnostics describe EOD quotes only. They establish")
    print("neither intraday execution quality nor an option-trading edge.")
    print(
        "This dataset falls inside the registered discovery window "
        "AUGUST_2026_THETADATA and may not be reused for confirmation."
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
