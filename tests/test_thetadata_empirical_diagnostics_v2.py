from __future__ import annotations

import pytest

from src.research.thetadata_empirical_diagnostics import MatchedReturn, SpreadRow
from src.research.thetadata_empirical_diagnostics_v2 import (
    dte,
    dte_bucket,
    matched_entry_spread_to_mid,
    premium_bucket,
    quote_state,
    spread_bucket,
)


def test_zero_bid_maps_to_200_percent_spread_mid():
    row = SpreadRow(
        underlying="AAPL",
        trading_date="2026-08-28",
        expiration="2026-09-25",
        strike=225.0,
        right="PUT",
        bid=0.0,
        ask=0.10,
    )
    assert row.spread_to_mid == pytest.approx(2.0)
    assert quote_state(row) == "ZERO_BID"
    assert spread_bucket(row.spread_to_mid) == "200%"


def test_dte_bucket():
    assert dte("2026-08-28", "2026-09-04") == 7
    assert dte_bucket(7) == "7-14"
    assert dte_bucket(31) == "31-45"


def test_premium_bucket():
    assert premium_bucket(0.05) == "<0.10"
    assert premium_bucket(0.25) == "0.25-0.49"
    assert premium_bucket(10.0) == "10+"


def test_matched_entry_spread():
    item = MatchedReturn(
        underlying="AAPL",
        entry_date="2026-08-27",
        exit_date="2026-08-28",
        expiration="2026-09-25",
        strike=225.0,
        right="PUT",
        entry_bid=0.8,
        entry_ask=1.2,
        exit_bid=1.0,
        exit_ask=1.2,
    )
    assert matched_entry_spread_to_mid(item) == pytest.approx(0.4)
