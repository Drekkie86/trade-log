from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
import sqlite3
from pathlib import Path
from statistics import mean, median
from typing import Iterable, Sequence


@dataclass(frozen=True)
class SpreadRow:
    underlying: str
    trading_date: str
    expiration: str
    strike: float
    right: str
    bid: float
    ask: float

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0

    @property
    def spread(self) -> float:
        return self.ask - self.bid

    @property
    def spread_to_mid(self) -> float | None:
        mid = self.mid
        if mid <= 0:
            return None
        return self.spread / mid

    @property
    def half_spread_to_mid(self) -> float | None:
        value = self.spread_to_mid
        return None if value is None else value / 2.0


@dataclass(frozen=True)
class MatchedReturn:
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
    def mid_to_mid_return(self) -> float | None:
        entry = self.entry_mid
        if entry <= 0:
            return None
        return (self.exit_mid - entry) / entry

    @property
    def ask_to_bid_return(self) -> float | None:
        if self.entry_ask <= 0:
            return None
        return (self.exit_bid - self.entry_ask) / self.entry_ask

    @property
    def quoted_round_trip_drag(self) -> float | None:
        gross = self.mid_to_mid_return
        executable = self.ask_to_bid_return
        if gross is None or executable is None:
            return None
        return gross - executable


def _quantile(values: Sequence[float], q: float) -> float | None:
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


def summary(values: Iterable[float]) -> dict[str, float | int | None]:
    clean = [float(v) for v in values]
    if not clean:
        return {
            "n": 0,
            "mean": None,
            "median": None,
            "p10": None,
            "p25": None,
            "p75": None,
            "p90": None,
            "p95": None,
        }
    return {
        "n": len(clean),
        "mean": mean(clean),
        "median": median(clean),
        "p10": _quantile(clean, 0.10),
        "p25": _quantile(clean, 0.25),
        "p75": _quantile(clean, 0.75),
        "p90": _quantile(clean, 0.90),
        "p95": _quantile(clean, 0.95),
    }


def load_spread_rows(db_path: str | Path) -> tuple[SpreadRow, ...]:
    with sqlite3.connect(db_path) as connection:
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
            JOIN thetadata_eod_runs r
              ON r.run_id = o.run_id
            WHERE r.status = 'COMPLETED'
              AND o.bid IS NOT NULL
              AND o.ask IS NOT NULL
              AND o.ask >= o.bid
            ORDER BY
                r.trading_date,
                r.symbol,
                o.expiration,
                o.strike,
                o.right
            """
        ).fetchall()

    return tuple(
        SpreadRow(
            underlying=str(row[0]),
            trading_date=str(row[1]),
            expiration=str(row[2]),
            strike=float(row[3]),
            right=str(row[4]),
            bid=float(row[5]),
            ask=float(row[6]),
        )
        for row in rows
    )


def load_next_session_matches(
    db_path: str | Path,
) -> tuple[MatchedReturn, ...]:
    """
    Match identical contracts between each underlying's consecutive completed
    staging dates.

    This is next OBSERVED SESSION in the staging database, not yet an exchange-
    calendar-verified next trading day.
    """
    with sqlite3.connect(db_path) as connection:
        dates = connection.execute(
            """
            SELECT symbol, trading_date
            FROM thetadata_eod_runs
            WHERE status = 'COMPLETED'
            GROUP BY symbol, trading_date
            ORDER BY symbol, trading_date
            """
        ).fetchall()

        by_symbol: dict[str, list[str]] = {}
        for symbol, trading_date in dates:
            by_symbol.setdefault(str(symbol), []).append(str(trading_date))

        results: list[MatchedReturn] = []

        for symbol, symbol_dates in by_symbol.items():
            for entry_date, exit_date in zip(symbol_dates, symbol_dates[1:]):
                matched = connection.execute(
                    """
                    SELECT
                        a.expiration,
                        a.strike,
                        a.right,
                        a.bid,
                        a.ask,
                        b.bid,
                        b.ask
                    FROM thetadata_eod_option_rows a
                    JOIN thetadata_eod_runs ra
                      ON ra.run_id = a.run_id
                    JOIN thetadata_eod_option_rows b
                      ON b.underlying = a.underlying
                     AND b.expiration = a.expiration
                     AND b.strike = a.strike
                     AND b.right = a.right
                    JOIN thetadata_eod_runs rb
                      ON rb.run_id = b.run_id
                    WHERE ra.symbol = ?
                      AND rb.symbol = ?
                      AND ra.trading_date = ?
                      AND rb.trading_date = ?
                      AND ra.status = 'COMPLETED'
                      AND rb.status = 'COMPLETED'
                      AND a.bid IS NOT NULL
                      AND a.ask IS NOT NULL
                      AND b.bid IS NOT NULL
                      AND b.ask IS NOT NULL
                      AND a.ask >= a.bid
                      AND b.ask >= b.bid
                    """,
                    (symbol, symbol, entry_date, exit_date),
                ).fetchall()

                for row in matched:
                    results.append(
                        MatchedReturn(
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


def pearson_correlation(
    xs: Sequence[float],
    ys: Sequence[float],
) -> float | None:
    if len(xs) != len(ys):
        raise ValueError("Series lengths differ.")
    if len(xs) < 2:
        return None

    mx = mean(xs)
    my = mean(ys)

    dx = [x - mx for x in xs]
    dy = [y - my for y in ys]

    denom_x = sqrt(sum(v * v for v in dx))
    denom_y = sqrt(sum(v * v for v in dy))

    if denom_x == 0 or denom_y == 0:
        return None

    return sum(a * b for a, b in zip(dx, dy)) / (denom_x * denom_y)


def daily_underlying_mean_returns(
    matches: Sequence[MatchedReturn],
    *,
    return_kind: str,
) -> dict[tuple[str, str], float]:
    grouped: dict[tuple[str, str], list[float]] = {}

    for item in matches:
        if return_kind == "mid_to_mid":
            value = item.mid_to_mid_return
        elif return_kind == "ask_to_bid":
            value = item.ask_to_bid_return
        else:
            raise ValueError(
                "return_kind must be 'mid_to_mid' or 'ask_to_bid'"
            )

        if value is None:
            continue

        grouped.setdefault(
            (item.underlying, item.entry_date),
            [],
        ).append(value)

    return {
        key: mean(values)
        for key, values in grouped.items()
        if values
    }


def cross_underlying_daily_correlations(
    matches: Sequence[MatchedReturn],
    *,
    return_kind: str = "mid_to_mid",
) -> dict[tuple[str, str], dict[str, float | int | None]]:
    daily = daily_underlying_mean_returns(
        matches,
        return_kind=return_kind,
    )

    symbols = sorted({symbol for symbol, _ in daily})
    result: dict[tuple[str, str], dict[str, float | int | None]] = {}

    for i, left in enumerate(symbols):
        for right in symbols[i + 1:]:
            left_by_date = {
                d: value
                for (symbol, d), value in daily.items()
                if symbol == left
            }
            right_by_date = {
                d: value
                for (symbol, d), value in daily.items()
                if symbol == right
            }

            common_dates = sorted(set(left_by_date) & set(right_by_date))
            xs = [left_by_date[d] for d in common_dates]
            ys = [right_by_date[d] for d in common_dates]

            result[(left, right)] = {
                "n_days": len(common_dates),
                "pearson": pearson_correlation(xs, ys),
            }

    return result
