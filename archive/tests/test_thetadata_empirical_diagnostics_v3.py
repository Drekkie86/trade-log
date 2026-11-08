"""
Tests for diagnostics v3.

The central test is
`test_expiry_contamination_reproduces_the_v2_artifact`: it builds a
synthetic staging database whose ground truth is known, shows that the
v1/v2 matching rule produces the -1.000 median that appeared in the real
output, and shows that the v3 partition removes it.

That is the difference between asserting a bug and demonstrating one.
"""

from __future__ import annotations

import sqlite3
from statistics import median

import pytest

from src.research.thetadata_empirical_diagnostics_v3 import (
    MatchedPairV3,
    count_eligible_entry_rows,
    dependence_report,
    fisher_interval,
    load_matched_pairs_v3,
    log_moneyness,
    moneyness_band,
    partition_pairs,
    pearson,
    synthetic_forwards,
    zero_move_fraction,
)

SCHEMA = """
CREATE TABLE thetadata_eod_runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    trading_date TEXT NOT NULL,
    requested_max_dte INTEGER NOT NULL,
    started_at_utc TEXT NOT NULL,
    completed_at_utc TEXT,
    status TEXT NOT NULL,
    row_count INTEGER,
    error_text TEXT,
    UNIQUE(symbol, trading_date, requested_max_dte)
);

CREATE TABLE thetadata_eod_option_rows (
    row_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES thetadata_eod_runs(run_id),
    provider TEXT NOT NULL,
    underlying TEXT NOT NULL,
    expiration TEXT NOT NULL,
    strike REAL NOT NULL,
    right TEXT NOT NULL,
    bid REAL, ask REAL, bid_size REAL, ask_size REAL,
    bid_exchange INTEGER, ask_exchange INTEGER,
    bid_condition INTEGER, ask_condition INTEGER,
    open REAL, high REAL, low REAL, close REAL, volume REAL, count REAL,
    provider_created TEXT, provider_last_trade TEXT,
    raw_json TEXT NOT NULL,
    UNIQUE(run_id, underlying, expiration, strike, right)
);
"""


class StagingBuilder:
    def __init__(self, path):
        self.connection = sqlite3.connect(path)
        self.connection.executescript(SCHEMA)
        self.runs: dict[tuple[str, str], int] = {}

    def run(self, symbol: str, trading_date: str) -> int:
        key = (symbol, trading_date)
        if key not in self.runs:
            cursor = self.connection.execute(
                """
                INSERT INTO thetadata_eod_runs
                    (symbol, trading_date, requested_max_dte,
                     started_at_utc, status, row_count)
                VALUES (?, ?, 45, '2026-08-29T00:00:00Z', 'COMPLETED', 0)
                """,
                (symbol, trading_date),
            )
            self.runs[key] = int(cursor.lastrowid)
        return self.runs[key]

    def row(
        self,
        symbol,
        trading_date,
        expiration,
        strike,
        right,
        bid,
        ask,
    ):
        self.connection.execute(
            """
            INSERT INTO thetadata_eod_option_rows
                (run_id, provider, underlying, expiration, strike, right,
                 bid, ask, raw_json)
            VALUES (?, 'THETADATA', ?, ?, ?, ?, ?, ?, '{}')
            """,
            (
                self.run(symbol, trading_date),
                symbol,
                expiration,
                strike,
                right,
                bid,
                ask,
            ),
        )

    def close(self):
        self.connection.commit()
        self.connection.close()


@pytest.fixture
def contaminated_db(tmp_path):
    """
    Two sessions. Two populations of cheap OTM calls.

    Population A expires on the exit date and settles worthless: the
    exit bid is zero, so ask-to-bid is exactly -1.000.

    Population B expires later and simply drifts a little.

    Both are cheap, so under the v1/v2 rule they land in the same entry
    ask bucket and A dominates the median.
    """
    path = tmp_path / "staging.db"
    builder = StagingBuilder(path)

    for i in range(60):
        strike = 300.0 + i
        builder.row("AAPL", "2026-08-27", "2026-08-28", strike, "CALL", 1.40, 1.50)
        builder.row("AAPL", "2026-08-28", "2026-08-28", strike, "CALL", 0.00, 0.01)

    for i in range(40):
        strike = 300.0 + i
        builder.row("AAPL", "2026-08-27", "2026-09-18", strike, "CALL", 1.40, 1.50)
        builder.row("AAPL", "2026-08-28", "2026-09-18", strike, "CALL", 1.35, 1.45)

    builder.close()
    return path


def test_expiry_contamination_reproduces_the_v2_artifact(contaminated_db):
    pairs = load_matched_pairs_v3(contaminated_db)
    assert len(pairs) == 100

    # The v1/v2 rule: pool everything.
    pooled = [
        p.ask_to_bid_return
        for p in pairs
        if p.ask_to_bid_return is not None
    ]
    assert median(pooled) == pytest.approx(-1.0)

    # v3: separate the estimands.
    split = partition_pairs(pairs)
    assert len(split["HELD_TO_EXPIRY"]) == 60
    assert len(split["ONE_SESSION"]) == 40

    one_session = [
        p.ask_to_bid_return for p in split["ONE_SESSION"]
    ]
    expiry = [p.ask_to_bid_return for p in split["HELD_TO_EXPIRY"]]

    assert median(expiry) == pytest.approx(-1.0)
    assert median(one_session) == pytest.approx(-0.10, abs=0.01)


def test_spans_expiry_boundary_is_inclusive():
    """A contract observed ON its expiration date has already settled."""
    pair = MatchedPairV3(
        underlying="AAPL",
        entry_date="2026-08-27",
        exit_date="2026-08-28",
        expiration="2026-08-28",
        strike=300.0,
        right="CALL",
        entry_bid=1.40,
        entry_ask=1.50,
        exit_bid=0.0,
        exit_ask=0.01,
    )
    assert pair.spans_expiry is True


def test_calendar_days_elapsed_detects_weekend_rolls():
    friday_to_monday = MatchedPairV3(
        "AAPL", "2026-08-21", "2026-08-24", "2026-09-18",
        300.0, "CALL", 1.0, 1.1, 1.0, 1.1,
    )
    assert friday_to_monday.calendar_days_elapsed == 3


def test_span_filter_excludes_weekend_pairs(contaminated_db):
    pairs = load_matched_pairs_v3(contaminated_db)
    split = partition_pairs(pairs, calendar_days=1)
    assert len(split["EXCLUDED_BY_SPAN"]) == 0

    weekend = MatchedPairV3(
        "AAPL", "2026-08-21", "2026-08-24", "2026-09-18",
        300.0, "CALL", 1.0, 1.1, 1.0, 1.1,
    )
    split = partition_pairs([weekend], calendar_days=1)
    assert len(split["EXCLUDED_BY_SPAN"]) == 1
    assert len(split["ONE_SESSION"]) == 0


# =====================================================================
# Parity forward
# =====================================================================

@pytest.fixture
def parity_db(tmp_path):
    """Chain built around a known forward of 300."""
    path = tmp_path / "parity.db"
    builder = StagingBuilder(path)

    forward = 300.0
    for strike in (280.0, 290.0, 300.0, 310.0, 320.0):
        call = max(forward - strike, 0.0) + 5.0
        put = call - (forward - strike)
        builder.row("AAPL", "2026-08-28", "2026-09-18", strike, "CALL",
                    call - 0.05, call + 0.05)
        builder.row("AAPL", "2026-08-28", "2026-09-18", strike, "PUT",
                    put - 0.05, put + 0.05)

    builder.close()
    return path


def test_parity_recovers_the_forward(parity_db):
    forwards = synthetic_forwards(parity_db)
    key = ("AAPL", "2026-08-28", "2026-09-18")
    assert key in forwards
    assert forwards[key].forward == pytest.approx(300.0, abs=0.01)
    assert forwards[key].strikes_used == 5


def test_parity_needs_enough_paired_strikes(parity_db):
    forwards = synthetic_forwards(parity_db, min_strikes=99)
    assert forwards == {}


def test_moneyness_bands_label_the_extreme_wing():
    assert moneyness_band(300.0, 300.0, "CALL") == "NEAR_ATM"
    assert moneyness_band(110.0, 320.0, "CALL") == "EXTREME_ITM"
    assert moneyness_band(110.0, 320.0, "PUT") == "EXTREME_OTM"
    assert moneyness_band(340.0, 320.0, "CALL") == "MODERATE_OTM"


def test_log_moneyness_rejects_nonsense():
    assert log_moneyness(0.0, 300.0) is None
    assert log_moneyness(300.0, 0.0) is None


# =====================================================================
# Dependence
# =====================================================================

def test_fisher_interval_is_wide_at_nineteen_days():
    """
    The interval that should have prevented the v1/v2 correlation from
    being promoted in either direction.
    """
    low, high = fisher_interval(0.489, 19)
    assert low == pytest.approx(0.045, abs=0.01)
    assert high == pytest.approx(0.772, abs=0.01)

    low, high = fisher_interval(-0.058, 19)
    assert low < 0 < high


def test_median_is_pinned_when_most_quotes_do_not_move():
    """
    Demonstrates N4 directly: a population where 60% of mids are
    unchanged has a daily median of exactly zero regardless of the
    movers, while the mean still reflects them.
    """
    pairs = []
    for i in range(60):
        pairs.append(
            MatchedPairV3("AAPL", "2026-08-27", "2026-08-28", "2026-09-18",
                          300.0 + i, "CALL", 1.0, 1.2, 1.0, 1.2)
        )
    for i in range(40):
        pairs.append(
            MatchedPairV3("AAPL", "2026-08-27", "2026-08-28", "2026-09-18",
                          400.0 + i, "CALL", 1.0, 1.2, 1.5, 1.7)
        )

    assert zero_move_fraction(pairs) == pytest.approx(0.60)

    from src.research.thetadata_empirical_diagnostics_v3 import daily_statistic

    med = daily_statistic(pairs, statistic="median")
    mean = daily_statistic(pairs, statistic="mean")

    assert med[("AAPL", "2026-08-27")] == pytest.approx(0.0)
    assert mean[("AAPL", "2026-08-27")] > 0.15


def test_dependence_report_gives_both_estimators_and_never_selects():
    pairs = []
    for day, (a_move, b_move) in enumerate(
        [(0.10, 0.10), (-0.05, -0.06), (0.02, 0.03), (0.08, 0.07)]
    ):
        entry_date = f"2026-08-{3 + day:02d}"
        exit_date = f"2026-08-{4 + day:02d}"
        for symbol, move in (("AAPL", a_move), ("JPM", b_move)):
            for i in range(5):
                pairs.append(
                    MatchedPairV3(
                        symbol, entry_date, exit_date, "2026-09-18",
                        300.0 + i, "CALL",
                        0.95, 1.05,
                        0.95 * (1 + move), 1.05 * (1 + move),
                    )
                )

    report = dependence_report(pairs)
    statistics = {estimate.statistic for estimate in report}

    assert statistics == {"mean", "median"}
    assert all(estimate.n_days == 4 for estimate in report)


def test_pearson_refuses_degenerate_input():
    assert pearson([1.0, 1.0, 1.0], [1.0, 2.0, 3.0]) is None
    assert pearson([1.0], [1.0]) is None


def test_accounting_invariant_detects_partial_exit_quote(tmp_path):
    """A present-but-partial exit quote must not disappear silently."""
    path = tmp_path / "partial.db"
    builder = StagingBuilder(path)
    builder.row(
        "AAPL", "2026-08-27", "2026-09-18", 300.0, "CALL", 1.00, 1.10
    )
    builder.row(
        "AAPL", "2026-08-28", "2026-09-18", 300.0, "CALL", None, 1.05
    )
    builder.close()

    matched = load_matched_pairs_v3(path)
    from src.research.thetadata_empirical_diagnostics_v3 import classify_unmatched_entries
    unmatched = classify_unmatched_entries(path)
    eligible = count_eligible_entry_rows(path)

    assert eligible == 1
    assert len(matched) == 0
    assert len(unmatched) == 0
    assert eligible != len(matched) + len(unmatched)
