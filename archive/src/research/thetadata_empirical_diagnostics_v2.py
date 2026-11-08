from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from statistics import mean, median
from typing import Iterable, Sequence

from src.research.thetadata_empirical_diagnostics import (
    MatchedReturn,
    SpreadRow,
    load_next_session_matches,
    load_spread_rows,
    pearson_correlation,
    summary,
)


def safe_ratio(numerator: float, denominator: float) -> float | None:
    if denominator <= 0:
        return None
    return numerator / denominator


def dte(entry_date: str, expiration: str) -> int:
    return (
        date.fromisoformat(expiration)
        - date.fromisoformat(entry_date)
    ).days


def dte_bucket(days: int) -> str:
    if days < 0:
        return "EXPIRED"
    if days <= 6:
        return "0-6"
    if days <= 14:
        return "7-14"
    if days <= 30:
        return "15-30"
    if days <= 45:
        return "31-45"
    return "46+"


def premium_bucket(value: float) -> str:
    if value <= 0:
        return "<=0"
    if value < 0.10:
        return "<0.10"
    if value < 0.25:
        return "0.10-0.24"
    if value < 0.50:
        return "0.25-0.49"
    if value < 1.00:
        return "0.50-0.99"
    if value < 2.50:
        return "1.00-2.49"
    if value < 5.00:
        return "2.50-4.99"
    if value < 10.00:
        return "5.00-9.99"
    return "10+"


def spread_bucket(spread_to_mid: float | None) -> str:
    if spread_to_mid is None:
        return "UNDEFINED"
    if spread_to_mid <= 0.05:
        return "<=5%"
    if spread_to_mid <= 0.10:
        return "5-10%"
    if spread_to_mid <= 0.25:
        return "10-25%"
    if spread_to_mid <= 0.50:
        return "25-50%"
    if spread_to_mid < 1.00:
        return "50-100%"
    if spread_to_mid < 2.00:
        return "100-200%"
    return "200%"


def quote_state(row: SpreadRow) -> str:
    if row.bid <= 0 and row.ask > 0:
        return "ZERO_BID"
    if row.bid == 0 and row.ask == 0:
        return "ZERO_BID_ASK"
    if row.ask <= 0:
        return "NONPOSITIVE_ASK"
    return "POSITIVE_TWO_SIDED"


def matched_entry_spread_to_mid(item: MatchedReturn) -> float | None:
    mid = item.entry_mid
    return safe_ratio(item.entry_ask - item.entry_bid, mid)


def matched_exit_spread_to_mid(item: MatchedReturn) -> float | None:
    mid = item.exit_mid
    return safe_ratio(item.exit_ask - item.exit_bid, mid)


def matched_quote_state(item: MatchedReturn) -> str:
    if item.entry_bid <= 0:
        return "ENTRY_ZERO_BID"
    if item.exit_bid <= 0:
        return "EXIT_ZERO_BID"
    return "POSITIVE_BID_BOTH_DAYS"


def group_summary(
    rows: Sequence[MatchedReturn],
    key_fn,
    value_fn,
) -> dict[str, dict[str, float | int | None]]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        value = value_fn(row)
        if value is None:
            continue
        grouped[str(key_fn(row))].append(float(value))
    return {
        key: summary(values)
        for key, values in sorted(grouped.items())
    }


def daily_robust_underlying_returns(
    matches: Sequence[MatchedReturn],
    *,
    return_kind: str,
    statistic: str = "median",
    require_positive_bids: bool = False,
    max_entry_spread_to_mid: float | None = None,
) -> dict[tuple[str, str], float]:
    grouped: dict[tuple[str, str], list[float]] = defaultdict(list)

    for item in matches:
        if require_positive_bids and (
            item.entry_bid <= 0 or item.exit_bid <= 0
        ):
            continue

        entry_spread = matched_entry_spread_to_mid(item)
        if (
            max_entry_spread_to_mid is not None
            and (
                entry_spread is None
                or entry_spread > max_entry_spread_to_mid
            )
        ):
            continue

        if return_kind == "mid_to_mid":
            value = item.mid_to_mid_return
        elif return_kind == "ask_to_bid":
            value = item.ask_to_bid_return
        else:
            raise ValueError("unsupported return_kind")

        if value is None:
            continue

        grouped[(item.underlying, item.entry_date)].append(value)

    reducer = median if statistic == "median" else mean
    return {
        key: reducer(values)
        for key, values in grouped.items()
        if values
    }


def cross_underlying_robust_correlations(
    matches: Sequence[MatchedReturn],
    *,
    return_kind: str = "mid_to_mid",
    statistic: str = "median",
    require_positive_bids: bool = False,
    max_entry_spread_to_mid: float | None = None,
) -> dict[tuple[str, str], dict[str, float | int | None]]:
    daily = daily_robust_underlying_returns(
        matches,
        return_kind=return_kind,
        statistic=statistic,
        require_positive_bids=require_positive_bids,
        max_entry_spread_to_mid=max_entry_spread_to_mid,
    )
    symbols = sorted({symbol for symbol, _ in daily})
    result = {}

    for i, left in enumerate(symbols):
        for right in symbols[i + 1:]:
            left_map = {
                d: value
                for (symbol, d), value in daily.items()
                if symbol == left
            }
            right_map = {
                d: value
                for (symbol, d), value in daily.items()
                if symbol == right
            }
            common = sorted(set(left_map) & set(right_map))
            xs = [left_map[d] for d in common]
            ys = [right_map[d] for d in common]
            result[(left, right)] = {
                "n_days": len(common),
                "pearson": pearson_correlation(xs, ys),
            }

    return result
