from __future__ import annotations

import pytest

from src.research.thetadata_empirical_diagnostics import (
    MatchedReturn,
    SpreadRow,
    cross_underlying_daily_correlations,
    pearson_correlation,
)


def test_spread_normalization():
    row = SpreadRow(
        underlying="AAPL",
        trading_date="2026-08-28",
        expiration="2026-09-25",
        strike=225.0,
        right="PUT",
        bid=0.01,
        ask=0.09,
    )

    assert row.mid == pytest.approx(0.05)
    assert row.spread == pytest.approx(0.08)
    assert row.spread_to_mid == pytest.approx(1.6)
    assert row.half_spread_to_mid == pytest.approx(0.8)


def test_matched_returns():
    row = MatchedReturn(
        underlying="AAPL",
        entry_date="2026-08-27",
        exit_date="2026-08-28",
        expiration="2026-09-25",
        strike=225.0,
        right="PUT",
        entry_bid=1.0,
        entry_ask=1.2,
        exit_bid=1.3,
        exit_ask=1.5,
    )

    assert row.entry_mid == pytest.approx(1.1)
    assert row.exit_mid == pytest.approx(1.4)
    assert row.mid_to_mid_return == pytest.approx(0.3 / 1.1)
    assert row.ask_to_bid_return == pytest.approx(0.1 / 1.2)


def test_pearson_perfect_positive():
    assert pearson_correlation(
        [1.0, 2.0, 3.0],
        [2.0, 4.0, 6.0],
    ) == pytest.approx(1.0)


def test_cross_underlying_daily_correlations():
    matches = []

    for day, a_ret, b_ret in (
        ("2026-08-03", 0.1, 0.2),
        ("2026-08-04", 0.2, 0.4),
        ("2026-08-05", 0.3, 0.6),
    ):
        matches.append(
            MatchedReturn(
                underlying="AAPL",
                entry_date=day,
                exit_date=day,
                expiration="2026-09-18",
                strike=100.0,
                right="CALL",
                entry_bid=0.9,
                entry_ask=1.0,
                exit_bid=1.0 + a_ret,
                exit_ask=1.0 + a_ret,
            )
        )
        matches.append(
            MatchedReturn(
                underlying="XOM",
                entry_date=day,
                exit_date=day,
                expiration="2026-09-18",
                strike=100.0,
                right="CALL",
                entry_bid=0.9,
                entry_ask=1.0,
                exit_bid=1.0 + b_ret,
                exit_ask=1.0 + b_ret,
            )
        )

    result = cross_underlying_daily_correlations(matches)
    cell = result[("AAPL", "XOM")]

    assert cell["n_days"] == 3
    assert cell["pearson"] == pytest.approx(1.0)
