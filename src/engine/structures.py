"""Defined-risk option structures, fills, payoffs and candidate generation.

Families (all with bounded loss):
  CREDIT_SPREAD  - short put spread / short call spread
  DEBIT_SPREAD   - long call spread / long put spread
  IRON_CONDOR    - short put spread + short call spread
  IRON_FLY       - short ATM straddle + long wings

Fills are modelled per leg: buy at mid + s * half-spread, sell at
mid - s * half-spread (s = slippage fraction). Commission is charged per
contract per leg at entry. Structures are held to expiry and settled at
intrinsic value; early assignment on American single-stock options is not
modelled.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

import numpy as np

from src.engine.chains import Expiry, Quote

MULTIPLIER = 100

CREDIT_SPREAD = "CREDIT_SPREAD"
DEBIT_SPREAD = "DEBIT_SPREAD"
IRON_CONDOR = "IRON_CONDOR"
IRON_FLY = "IRON_FLY"
FAMILIES = (CREDIT_SPREAD, DEBIT_SPREAD, IRON_CONDOR, IRON_FLY)

FAMILY_LABELS = {
    CREDIT_SPREAD: "Credit spread",
    DEBIT_SPREAD: "Debit spread",
    IRON_CONDOR: "Iron condor",
    IRON_FLY: "Iron fly",
}


@dataclass(frozen=True)
class Leg:
    quote: Quote
    side: int  # +1 buy, -1 sell

    @property
    def right(self) -> str:
        return self.quote.right

    @property
    def strike(self) -> float:
        return self.quote.strike

    def fill(self, slippage: float) -> float:
        q = self.quote
        half = 0.5 * (q.ask - q.bid)
        return q.mid + slippage * half if self.side > 0 else q.mid - slippage * half

    def payoff(self, prices: np.ndarray) -> np.ndarray:
        if self.right == "C":
            intrinsic = np.maximum(prices - self.strike, 0.0)
        else:
            intrinsic = np.maximum(self.strike - prices, 0.0)
        return self.side * intrinsic


@dataclass(frozen=True)
class Structure:
    family: str
    shape: str
    underlying: str
    expiration: str
    legs: tuple[Leg, ...]

    @property
    def key(self) -> str:
        legs = ",".join(
            f"{'B' if l.side > 0 else 'S'}{l.right}{l.strike:g}"
            for l in sorted(self.legs, key=lambda l: (l.strike, l.right, l.side))
        )
        return f"{self.underlying}|{self.expiration}|{self.shape}|{legs}"

    @property
    def strikes(self) -> list[float]:
        return sorted({l.strike for l in self.legs})

    def describe(self) -> str:
        parts = [
            f"{'Buy' if l.side > 0 else 'Sell'} {l.strike:g}{l.right}"
            for l in sorted(self.legs, key=lambda l: (l.strike, l.right))
        ]
        return " / ".join(parts)

    def entry_cash_per_share(self, slippage: float) -> float:
        """Cash received (+) or paid (-) per share at entry, before commission."""
        return float(sum(-l.side * l.fill(slippage) for l in self.legs))

    def payoff_per_share(self, prices: np.ndarray) -> np.ndarray:
        total = np.zeros_like(prices, dtype=float)
        for leg in self.legs:
            total = total + leg.payoff(prices)
        return total

    def breakpoints(self) -> np.ndarray:
        ks = self.strikes
        return np.array([0.0] + ks + [ks[-1] * 4.0])


@dataclass(frozen=True)
class CostPolicy:
    slippage_fraction: float = 0.5
    commission_per_contract: float = 0.65

    def commission(self, structure: Structure) -> float:
        return self.commission_per_contract * len(structure.legs)


def pnl(structure: Structure, prices: np.ndarray, cost: CostPolicy) -> np.ndarray:
    """Hold-to-expiry P&L in USD for one lot at the given terminal prices."""
    entry = structure.entry_cash_per_share(cost.slippage_fraction) * MULTIPLIER
    return structure.payoff_per_share(prices) * MULTIPLIER + entry - cost.commission(structure)


# ------------------------------------------------------------------ generation
@dataclass(frozen=True)
class GenerationGrid:
    short_deltas: tuple[float, ...] = (0.10, 0.16, 0.20, 0.25, 0.30)
    long_deltas: tuple[float, ...] = (0.35, 0.45, 0.55)
    width_steps: tuple[int, ...] = (1, 2, 3, 5)
    fly_wing_steps: tuple[int, ...] = (2, 4, 6)
    families: tuple[str, ...] = FAMILIES


def _by_delta(quotes: Sequence[Quote], target: float) -> Quote | None:
    usable = [q for q in quotes if q.delta is not None]
    if not usable:
        return None
    best = min(usable, key=lambda q: abs(abs(q.delta) - target))
    return best if abs(abs(best.delta) - target) <= 0.06 else None


def _offset(sorted_quotes: Sequence[Quote], anchor: Quote, steps: int) -> Quote | None:
    strikes = [q.strike for q in sorted_quotes]
    i = strikes.index(anchor.strike) + steps
    return sorted_quotes[i] if 0 <= i < len(sorted_quotes) else None


def generate(underlying: str, expiry: Expiry, grid: GenerationGrid) -> list[Structure]:
    if expiry.forward is None:
        return []
    calls = sorted((q for q in expiry.quotes if q.right == "C" and q.two_sided),
                   key=lambda q: q.strike)
    puts = sorted((q for q in expiry.quotes if q.right == "P" and q.two_sided),
                  key=lambda q: q.strike)
    exp = expiry.expiration
    out: dict[str, Structure] = {}

    def add(s: Structure | None) -> None:
        if s is not None and len({l.strike for l in s.legs}) >= 2:
            out.setdefault(s.key, s)

    def put_credit(d: float, w: int) -> Structure | None:
        short = _by_delta([q for q in puts if q.strike < expiry.forward], d)
        long = short and _offset(puts, short, -w)
        return long and Structure(CREDIT_SPREAD, "PUT_CREDIT_SPREAD", underlying, exp,
                                  (Leg(short, -1), Leg(long, +1)))

    def call_credit(d: float, w: int) -> Structure | None:
        short = _by_delta([q for q in calls if q.strike > expiry.forward], d)
        long = short and _offset(calls, short, +w)
        return long and Structure(CREDIT_SPREAD, "CALL_CREDIT_SPREAD", underlying, exp,
                                  (Leg(short, -1), Leg(long, +1)))

    for d in grid.short_deltas:
        for w in grid.width_steps:
            pc, cc = put_credit(d, w), call_credit(d, w)
            if CREDIT_SPREAD in grid.families:
                add(pc)
                add(cc)
            if IRON_CONDOR in grid.families and pc and cc:
                add(Structure(IRON_CONDOR, "IRON_CONDOR", underlying, exp, pc.legs + cc.legs))

    if DEBIT_SPREAD in grid.families:
        for d in grid.long_deltas:
            for w in grid.width_steps:
                lc = _by_delta(calls, d)
                sc = lc and _offset(calls, lc, +w)
                if sc:
                    add(Structure(DEBIT_SPREAD, "CALL_DEBIT_SPREAD", underlying, exp,
                                  (Leg(lc, +1), Leg(sc, -1))))
                lp = _by_delta(puts, d)
                sp = lp and _offset(puts, lp, -w)
                if sp:
                    add(Structure(DEBIT_SPREAD, "PUT_DEBIT_SPREAD", underlying, exp,
                                  (Leg(lp, +1), Leg(sp, -1))))

    if IRON_FLY in grid.families and calls and puts:
        common = sorted({q.strike for q in calls} & {q.strike for q in puts})
        if common:
            atm = min(common, key=lambda k: abs(k - expiry.forward))
            sc = next(q for q in calls if q.strike == atm)
            sp = next(q for q in puts if q.strike == atm)
            for w in grid.fly_wing_steps:
                lc, lp = _offset(calls, sc, +w), _offset(puts, sp, -w)
                if lc and lp:
                    add(Structure(IRON_FLY, "IRON_FLY", underlying, exp,
                                  (Leg(lp, +1), Leg(sp, -1), Leg(sc, -1), Leg(lc, +1))))
    return list(out.values())


def liquid(structure: Structure, *, max_relative_spread: float, min_bid: float,
           min_open_interest: int = 0) -> str | None:
    """Return a rejection reason, or None when every leg has a real two-sided market.

    Fails closed: a leg with no bid, a bid under ``min_bid`` or a spread wider than
    ``max_relative_spread`` of its mid is not something the engine may price at mid.
    Open interest is only checked when the provider supplies it.
    """
    for leg in structure.legs:
        q = leg.quote
        if not q.two_sided:
            return "ONE_SIDED_QUOTE"
        if q.bid < min_bid:
            return "NO_REAL_MARKET"
        if q.relative_spread > max_relative_spread:
            return "WIDE_SPREAD"
        if min_open_interest and q.open_interest is not None and q.open_interest < min_open_interest:
            return "LOW_OPEN_INTEREST"
    return None


def iter_structures(underlying: str, expiries: Iterable[Expiry],
                    grid: GenerationGrid) -> Iterable[tuple[Expiry, Structure]]:
    for expiry in expiries:
        for s in generate(underlying, expiry, grid):
            yield expiry, s
