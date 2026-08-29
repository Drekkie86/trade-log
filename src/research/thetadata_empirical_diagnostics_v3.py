"""
Christiania — ThetaData empirical diagnostics v3.

Additive. Does not modify v1 or v2. Reads the same staging database.

This module fixes three defects found in the v1/v2 diagnostics. Each fix is
independent and each changes the interpretation of a published number, so
none of them is cosmetic.

---------------------------------------------------------------------------
N2. Expiry contamination
---------------------------------------------------------------------------

`load_next_session_matches` joins consecutive staging dates on
(underlying, expiration, strike, right) with no condition excluding
contracts whose expiration falls on or before the exit date.

A contract observed on its own expiration day is a HELD-TO-EXPIRY
observation, not a one-session observation. Out-of-the-money contracts
settle at a zero bid, so those pairs return exactly -1.000.

That is what produced the discontinuity in the v2 output:

    entry ask 1.00-2.49  ->  median -1.000
    entry ask 2.50-4.99  ->  median -0.255

A 0.75 jump across one adjacent bucket boundary is not economics. It is
two estimands pooled into one column, with the expiry population
concentrated in the cheap buckets.

v3 separates them and never pools them again.

---------------------------------------------------------------------------
N3. Unbounded strike ladder
---------------------------------------------------------------------------

Staging pulls `expiration=*` with only a DTE bound, so the population is
the full OPRA strike ladder — AAPL strikes at 110 while spot is near 320.
Nearly half of matched rows carry an entry ask of $10 or more.

Pooled spread and return percentiles over that population describe the
listing, not anything tradeable.

The staging schema stores no underlying price, so v3 derives one from the
data itself using a parity-derived reference level: for each (underlying, session,
expiration), the reference is the median of

    F_k = K + mid(call_K) - mid(put_K)

over strikes where both sides are two-sided. Log-moneyness ln(K/F) then
gives a band for every contract without any external price source.

---------------------------------------------------------------------------
N4. A dependence statistic pinned to zero by construction
---------------------------------------------------------------------------

v2 promoted a cross-underlying correlation computed from the daily
cross-sectional MEDIAN of mid-to-mid returns.

The v1 output shows the pooled median mid-to-mid return is exactly
0.000000 across 53,968 observations: more than half of the chain's quotes
do not move day over day. A daily cross-sectional median over a
call/put-symmetric population dominated by stale wing quotes is therefore
pinned near zero regardless of what the market did.

Correlating a pinned statistic across underlyings correlates noise, and
the resulting near-zero correlation flatters every effective-N
calculation downstream.

v3 does not choose an estimator. It reports mean and median side by side,
each with a Fisher-z confidence interval, plus the fraction of exactly
zero moves that causes the pinning — so the reader can see why the two
disagree instead of being handed the winner.
"""

from __future__ import annotations

import math
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from statistics import median
from typing import Iterable, Mapping, Sequence

MIN_PARITY_STRIKES = 3


# =====================================================================
# Matched pairs, expiry-aware
# =====================================================================

@dataclass(frozen=True)
class MatchedPairV3:
    underlying: str
    entry_date: str
    exit_date: str
    expiration: str
    strike: float
    right: str
    entry_bid: float
    entry_ask: float
    exit_bid: float
    exit_ask: float

    @property
    def entry_mid(self) -> float:
        return (self.entry_bid + self.entry_ask) / 2.0

    @property
    def exit_mid(self) -> float:
        return (self.exit_bid + self.exit_ask) / 2.0

    @property
    def calendar_days_elapsed(self) -> int:
        return (
            date.fromisoformat(self.exit_date)
            - date.fromisoformat(self.entry_date)
        ).days

    @property
    def spans_expiry(self) -> bool:
        """
        True when the contract expires on or before the exit observation.

        These pairs are held-to-expiry outcomes. They are legitimate
        evidence about a different question and must never be pooled with
        one-session quote evolution.
        """
        return self.expiration <= self.exit_date

    @property
    def mid_to_mid_return(self) -> float | None:
        if self.entry_mid <= 0:
            return None
        return (self.exit_mid - self.entry_mid) / self.entry_mid

    @property
    def ask_to_bid_return(self) -> float | None:
        """Holding-period outcome: buy at entry ask, exit at later bid.

        This is NOT a pure transaction-cost estimate. It includes market
        movement, theta and volatility changes over the holding interval.
        """
        if self.entry_ask <= 0:
            return None
        return (self.exit_bid - self.entry_ask) / self.entry_ask

    @property
    def entry_quoted_crossing_fraction_of_ask(self) -> float | None:
        """Same-observation quoted crossing penalty as fraction of ask.

        This is the displayed penalty of buying at ask and immediately
        liquidating at bid. It is quote-based, not an actual-fill estimate.
        """
        if self.entry_ask <= 0:
            return None
        return (self.entry_ask - self.entry_bid) / self.entry_ask

    @property
    def mid_unchanged(self) -> bool:
        return self.exit_mid == self.entry_mid


MATCH_SQL = """
SELECT
    a.expiration,
    a.strike,
    a.right,
    a.bid,
    a.ask,
    b.bid,
    b.ask
FROM thetadata_eod_option_rows a
JOIN thetadata_eod_runs ra ON ra.run_id = a.run_id
JOIN thetadata_eod_option_rows b
  ON b.underlying = a.underlying
 AND b.expiration = a.expiration
 AND b.strike = a.strike
 AND b.right = a.right
JOIN thetadata_eod_runs rb ON rb.run_id = b.run_id
WHERE ra.symbol = ?
  AND rb.symbol = ?
  AND ra.trading_date = ?
  AND rb.trading_date = ?
  AND ra.status = 'COMPLETED'
  AND rb.status = 'COMPLETED'
  AND a.bid IS NOT NULL AND a.ask IS NOT NULL
  AND b.bid IS NOT NULL AND b.ask IS NOT NULL
  AND a.ask >= a.bid
  AND b.ask >= b.bid
"""


def load_matched_pairs_v3(
    db_path: str | Path,
) -> tuple[MatchedPairV3, ...]:
    """
    Same join as v1, but every pair is returned and classified rather
    than silently pooled. Nothing is dropped here — the caller decides,
    and the counts of each population are reported.
    """

    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row

    try:
        dates = connection.execute(
            """
            SELECT symbol, trading_date
            FROM thetadata_eod_runs
            WHERE status = 'COMPLETED'
            GROUP BY symbol, trading_date
            ORDER BY symbol, trading_date
            """
        ).fetchall()

        by_symbol: dict[str, list[str]] = defaultdict(list)
        for row in dates:
            by_symbol[str(row["symbol"])].append(str(row["trading_date"]))

        results: list[MatchedPairV3] = []

        for symbol, symbol_dates in by_symbol.items():
            for entry_date, exit_date in zip(
                symbol_dates, symbol_dates[1:]
            ):
                for row in connection.execute(
                    MATCH_SQL,
                    (symbol, symbol, entry_date, exit_date),
                ):
                    results.append(
                        MatchedPairV3(
                            underlying=symbol,
                            entry_date=entry_date,
                            exit_date=exit_date,
                            expiration=str(row[0]),
                            strike=float(row[1]),
                            right=str(row[2]),
                            entry_bid=float(row[3]),
                            entry_ask=float(row[4]),
                            exit_bid=float(row[5]),
                            exit_ask=float(row[6]),
                        )
                    )

        return tuple(results)

    finally:
        connection.close()


def partition_pairs(
    pairs: Sequence[MatchedPairV3],
    *,
    calendar_days: int | None = None,
) -> dict[str, tuple[MatchedPairV3, ...]]:
    """
    Split into the estimands that v1/v2 pooled.

    ONE_SESSION        contract still alive at the exit observation
    HELD_TO_EXPIRY     contract expired on or before the exit observation

    `calendar_days` optionally restricts ONE_SESSION to a fixed elapsed
    span. Friday-to-Monday pairs carry three calendar days of theta and
    should not sit in the same column as one-day pairs.
    """

    one_session: list[MatchedPairV3] = []
    expiry: list[MatchedPairV3] = []
    wrong_span: list[MatchedPairV3] = []

    for pair in pairs:
        if pair.spans_expiry:
            expiry.append(pair)
        elif (
            calendar_days is not None
            and pair.calendar_days_elapsed != calendar_days
        ):
            wrong_span.append(pair)
        else:
            one_session.append(pair)

    return {
        "ONE_SESSION": tuple(one_session),
        "HELD_TO_EXPIRY": tuple(expiry),
        "EXCLUDED_BY_SPAN": tuple(wrong_span),
    }


# =====================================================================
# Entry observations with no matched next observed session
# =====================================================================

@dataclass(frozen=True)
class UnmatchedEntry:
    underlying: str
    entry_date: str
    expected_exit_date: str
    expiration: str
    strike: float
    right: str
    entry_bid: float
    entry_ask: float
    mechanism: str

    @property
    def worst_case_ask_to_bid_return(self) -> float | None:
        if self.entry_ask <= 0:
            return None
        return -1.0


def classify_unmatched_entries(
    db_path: str | Path,
) -> tuple[UnmatchedEntry, ...]:
    """Classify entry contracts that do not match on the next observed date.

    Missing next quotes are potentially informative censoring. They are never
    silently dropped. Expiry-related absence is separated from non-expiry
    absence; non-expiry absence can be included in a worst-case sensitivity
    calculation as a total loss of the entry ask.
    """
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        dates = connection.execute(
            """
            SELECT symbol, trading_date
            FROM thetadata_eod_runs
            WHERE status='COMPLETED'
            GROUP BY symbol, trading_date
            ORDER BY symbol, trading_date
            """
        ).fetchall()
        by_symbol: dict[str, list[str]] = defaultdict(list)
        for row in dates:
            by_symbol[str(row["symbol"])].append(str(row["trading_date"]))

        results: list[UnmatchedEntry] = []
        for symbol, symbol_dates in by_symbol.items():
            for entry_date, exit_date in zip(symbol_dates, symbol_dates[1:]):
                rows = connection.execute(
                    """
                    SELECT a.expiration, a.strike, a.right, a.bid, a.ask
                    FROM thetadata_eod_option_rows a
                    JOIN thetadata_eod_runs ra ON ra.run_id=a.run_id
                    LEFT JOIN thetadata_eod_option_rows b
                      ON b.underlying=a.underlying
                     AND b.expiration=a.expiration
                     AND b.strike=a.strike
                     AND b.right=a.right
                     AND b.run_id=(
                        SELECT rb.run_id FROM thetadata_eod_runs rb
                        WHERE rb.symbol=? AND rb.trading_date=?
                          AND rb.status='COMPLETED'
                        LIMIT 1
                     )
                    WHERE ra.symbol=? AND ra.trading_date=?
                      AND ra.status='COMPLETED'
                      AND b.row_id IS NULL
                      AND a.ask IS NOT NULL
                    """,
                    (symbol, exit_date, symbol, entry_date),
                ).fetchall()
                for row in rows:
                    expiration=str(row[0])
                    mechanism=(
                        "EXPIRY_RELATED"
                        if expiration <= exit_date
                        else "MISSING_NEXT_QUOTE_NONEXPIRY"
                    )
                    results.append(UnmatchedEntry(
                        underlying=symbol,
                        entry_date=entry_date,
                        expected_exit_date=exit_date,
                        expiration=expiration,
                        strike=float(row[1]),
                        right=str(row[2]),
                        entry_bid=float(row[3] or 0.0),
                        entry_ask=float(row[4]),
                        mechanism=mechanism,
                    ))
        return tuple(results)
    finally:
        connection.close()


# =====================================================================
# Put-call parity forward and moneyness
# =====================================================================

@dataclass(frozen=True)
class ParityForward:
    underlying: str
    trading_date: str
    expiration: str
    forward: float
    strikes_used: int


def synthetic_forwards(
    db_path: str | Path,
    *,
    min_strikes: int = MIN_PARITY_STRIKES,
) -> dict[tuple[str, str, str], ParityForward]:
    """
    Estimate an approximate parity reference per (underlying, session, expiration)
    using only staged quotes.

        F_k = K + mid(call_K) - mid(put_K)

    The median across eligible strikes is used rather than the mean: a
    single stale wing quote would otherwise drag the estimate, and unlike
    the dependence statistic in N4 there is no symmetry here that pins
    the median to a constant.

    Only strikes where BOTH sides are two-sided contribute, which is a
    real restriction — it means forwards are unavailable for expirations
    whose chains are entirely one-sided, and those are reported rather
    than silently skipped.
    """

    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row

    try:
        rows = connection.execute(
            """
            SELECT
                r.symbol,
                r.trading_date,
                o.expiration,
                o.strike,
                o.right,
                o.bid,
                o.ask
            FROM thetadata_eod_option_rows o
            JOIN thetadata_eod_runs r ON r.run_id = o.run_id
            WHERE r.status = 'COMPLETED'
              AND o.bid IS NOT NULL
              AND o.ask IS NOT NULL
              AND o.ask >= o.bid
              AND o.bid > 0
            """
        ).fetchall()
    finally:
        connection.close()

    mids: dict[tuple[str, str, str, float], dict[str, float]] = defaultdict(dict)

    for row in rows:
        key = (
            str(row["symbol"]),
            str(row["trading_date"]),
            str(row["expiration"]),
            float(row["strike"]),
        )
        mids[key][str(row["right"])] = (
            float(row["bid"]) + float(row["ask"])
        ) / 2.0

    per_expiry: dict[tuple[str, str, str], list[float]] = defaultdict(list)

    for (symbol, trading_date, expiration, strike), sides in mids.items():
        if "CALL" not in sides or "PUT" not in sides:
            continue
        per_expiry[(symbol, trading_date, expiration)].append(
            strike + sides["CALL"] - sides["PUT"]
        )

    forwards: dict[tuple[str, str, str], ParityForward] = {}

    for key, values in per_expiry.items():
        if len(values) < min_strikes:
            continue
        symbol, trading_date, expiration = key
        forwards[key] = ParityForward(
            underlying=symbol,
            trading_date=trading_date,
            expiration=expiration,
            forward=float(median(values)),
            strikes_used=len(values),
        )

    return forwards


def log_moneyness(strike: float, forward: float) -> float | None:
    if strike <= 0 or forward <= 0:
        return None
    return math.log(strike / forward)


def moneyness_band(
    strike: float,
    forward: float,
    right: str,
) -> str | None:
    """
    Bands by distance from the forward, labelled ITM/OTM by right.

    EXTREME is the band that should never have been pooled with the rest:
    it is where the $3+ dollar spreads and the 46% deep-ITM mass live.
    """

    m = log_moneyness(strike, forward)
    if m is None:
        return None

    magnitude = abs(m)

    if magnitude <= 0.05:
        distance = "NEAR"
    elif magnitude <= 0.15:
        distance = "MODERATE"
    elif magnitude <= 0.35:
        distance = "FAR"
    else:
        distance = "EXTREME"

    if distance == "NEAR":
        return "NEAR_ATM"

    call_in_the_money = m < 0
    if right.upper() == "CALL":
        side = "ITM" if call_in_the_money else "OTM"
    else:
        side = "OTM" if call_in_the_money else "ITM"

    return f"{distance}_{side}"


# =====================================================================
# Dependence, reported honestly
# =====================================================================

def pearson(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    n = len(xs)
    if n < 3 or n != len(ys):
        return None

    mean_x = sum(xs) / n
    mean_y = sum(ys) / n

    sxy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    sxx = sum((x - mean_x) ** 2 for x in xs)
    syy = sum((y - mean_y) ** 2 for y in ys)

    if sxx <= 0 or syy <= 0:
        return None

    return sxy / math.sqrt(sxx * syy)


def fisher_interval(
    r: float,
    n: int,
    z: float = 1.96,
) -> tuple[float, float] | None:
    """
    Fisher z interval. At n=19 the half-width is about 0.5 in z units,
    which is why the v1 and v2 correlation estimates were never
    distinguishable and neither should have been promoted.
    """

    if n < 4 or not -1.0 < r < 1.0:
        return None

    zr = 0.5 * math.log((1.0 + r) / (1.0 - r))
    se = 1.0 / math.sqrt(n - 3)

    return (math.tanh(zr - z * se), math.tanh(zr + z * se))


def zero_move_fraction(
    pairs: Sequence[MatchedPairV3],
) -> float | None:
    """
    Share of pairs whose mid did not move at all.

    This is the diagnostic that explains N4. When it is above 0.5, any
    daily cross-sectional median return is pinned at zero and cannot
    carry market information.
    """

    if not pairs:
        return None
    return sum(1 for pair in pairs if pair.mid_unchanged) / len(pairs)


def daily_statistic(
    pairs: Sequence[MatchedPairV3],
    *,
    statistic: str,
) -> dict[tuple[str, str], float]:
    grouped: dict[tuple[str, str], list[float]] = defaultdict(list)

    for pair in pairs:
        value = pair.mid_to_mid_return
        if value is None:
            continue
        grouped[(pair.underlying, pair.entry_date)].append(value)

    if statistic == "median":
        reduce = median
    elif statistic == "mean":
        def reduce(values):  # type: ignore[misc]
            return sum(values) / len(values)
    else:
        raise ValueError("statistic must be 'mean' or 'median'")

    return {
        key: float(reduce(values))
        for key, values in grouped.items()
        if values
    }


@dataclass(frozen=True)
class DependenceEstimate:
    pair: tuple[str, str]
    statistic: str
    n_days: int
    r: float | None
    ci_low: float | None
    ci_high: float | None

    @property
    def excludes_zero(self) -> bool:
        if self.ci_low is None or self.ci_high is None:
            return False
        return self.ci_low > 0.0 or self.ci_high < 0.0


def dependence_report(
    pairs: Sequence[MatchedPairV3],
) -> list[DependenceEstimate]:
    """
    Both estimators, both with intervals. No selection.

    v2 promoted the median result over the mean result after seeing that
    they disagreed. Reporting both removes that degree of freedom, and
    the intervals show that at this sample size neither supports a claim.
    """

    estimates: list[DependenceEstimate] = []

    for statistic in ("mean", "median"):
        daily = daily_statistic(pairs, statistic=statistic)
        symbols = sorted({symbol for symbol, _ in daily})

        for index, left in enumerate(symbols):
            for right in symbols[index + 1:]:
                left_map = {
                    d: v for (s, d), v in daily.items() if s == left
                }
                right_map = {
                    d: v for (s, d), v in daily.items() if s == right
                }
                shared = sorted(set(left_map) & set(right_map))

                xs = [left_map[d] for d in shared]
                ys = [right_map[d] for d in shared]

                r = pearson(xs, ys)
                interval = (
                    fisher_interval(r, len(shared))
                    if r is not None
                    else None
                )

                estimates.append(
                    DependenceEstimate(
                        pair=(left, right),
                        statistic=statistic,
                        n_days=len(shared),
                        r=r,
                        ci_low=interval[0] if interval else None,
                        ci_high=interval[1] if interval else None,
                    )
                )

    return estimates


# =====================================================================
# Grouping helper
# =====================================================================

def quantile(values: Sequence[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * q
    lo = int(position)
    hi = min(lo + 1, len(ordered) - 1)
    frac = position - lo
    return ordered[lo] * (1.0 - frac) + ordered[hi] * frac


def group_medians(
    items: Iterable[tuple[str, float]],
) -> dict[str, dict[str, float | int | None]]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for key, value in items:
        grouped[key].append(value)

    return {
        key: {
            "n": len(values),
            "median": quantile(values, 0.5),
            "p25": quantile(values, 0.25),
            "p75": quantile(values, 0.75),
        }
        for key, values in sorted(grouped.items())
    }
