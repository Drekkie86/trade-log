"""Stage-0 options strategy feasibility: pure, offline, no orders or DB writes.

Calculations are deterministic terminal-payoff mathematics on conservative
individual-leg ENTRY quotes. They are NOT verified package fills, forward
predictions, executable exits, broker margin approval, or positive expectancy.
Reuses Christiania's shadow structure_json contract via from_shadow_proposal().
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from typing import Any, Mapping

VERSION = "STRATEGY_FALSIFICATION_STAGE0_V1"
BANKROLL_EUR = Decimal("500")
CENTS = Decimal("0.01")

# A research family is not a predictive trading signal. Reference hedges are
# intentionally separated from the limited-capital candidates.
CATALOGUE: dict[str, tuple[str, str]] = {
    "S01": ("Covered call", "C_REFERENCE_HEDGE"),
    "S02": ("Married/protective put", "C_REFERENCE_HEDGE"),
    "S03": ("Bull call debit spread", "A_FEASIBILITY"),
    "S04": ("Bear put debit spread", "A_FEASIBILITY"),
    "S05": ("Protective collar", "C_REFERENCE_HEDGE"),
    "S06": ("Long straddle", "B_FEASIBILITY"),
    "S07": ("Long strangle", "B_FEASIBILITY"),
    "S08": ("Long 1/-2/1 butterfly", "A_FEASIBILITY"),
    "S09": ("Iron condor", "B_FEASIBILITY"),
    "S10": ("Iron butterfly", "B_FEASIBILITY"),
    "X11": ("Momentum + abnormal skew + IV/RV vertical", "A_FEASIBILITY"),
}
# Included only to ensure old Christiania evidence stays mathematically
# reviewable; NOT a twelfth catalogue strategy or an approved new hypothesis.
LEGACY_REVERSE_ID = "S08R_REFERENCE"


def dec(value: Any) -> Decimal:
    try:
        n = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"Invalid decimal value: {value!r}") from exc
    if not n.is_finite():
        raise ValueError("Non-finite numerical input")
    return n


def utc(value: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError("Timestamp missing")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("Timestamp must specify timezone")
    return result.astimezone(timezone.utc)


def money(value: Decimal) -> str:
    return str(value.quantize(CENTS))


@dataclass(frozen=True)
class Leg:
    kind: str                   # CALL, PUT, STOCK
    side: str                   # BUY, SELL at entry
    quantity: int               # number of contracts, or stock shares
    multiplier: Decimal         # option shares/contract; STOCK must be 1
    strike: Decimal | None      # None only for STOCK
    expiration: str | None      # None only for STOCK
    bid: Decimal | None
    ask: Decimal | None
    quote_at: str | None
    bid_size: Decimal | None = None
    ask_size: Decimal | None = None
    source_id: str | None = None


@dataclass(frozen=True)
class Structure:
    strategy_id: str
    signal_version: str
    decision_at: str
    legs: tuple[Leg, ...]
    reference: str | None = None


@dataclass(frozen=True)
class QuoteCostPolicy:
    # None means unknown, NEVER free. These are scenario inputs and may be
    # assumed; actual Saxo costs require independent broker verification.
    option_cost_per_contract_side_usd: Decimal | None
    stock_round_trip_cost_usd: Decimal | None
    eur_to_usd: Decimal | None
    cost_provenance: str | None
    fx_provenance: str | None
    max_quote_age_seconds: int | None
    verified_share_inventory: bool = False
    bankroll_eur: Decimal = BANKROLL_EUR
    max_leg_quote_skew_seconds: int | None = None
    additional_round_trip_cost_usd: Decimal | None = None  # slippage, fees and FX cost budget
    tax_cost_usd: Decimal | None = None
    fx_observed_at: str | None = None


@dataclass(frozen=True)
class Feasibility:
    strategy_id: str
    state: str
    reasons: tuple[str, ...]
    gross_max_loss_usd: str | None
    gross_max_profit_usd: str | None  # null if unlimited upside
    unlimited_profit: bool
    entry_cashflow_usd: str | None
    round_trip_cost_usd: str | None
    conservative_capital_eur: str | None
    breakevens_usd: tuple[str, ...]  # gross expiry spot break-even, USD/share
    net_breakevens_usd: tuple[str, ...] = () # after assumed full round trip costs

    def as_dict(self) -> dict[str, Any]:
        from dataclasses import asdict
        result = asdict(self)
        if self.gross_max_loss_usd is not None and self.round_trip_cost_usd is not None:
            result["net_max_loss_usd"] = money(dec(self.gross_max_loss_usd) + dec(self.round_trip_cost_usd))
            result["net_max_profit_usd"] = (
                None if self.unlimited_profit else money(
                    dec(self.gross_max_profit_usd) - dec(self.round_trip_cost_usd)))
        else:
            result["net_max_loss_usd"] = None
            result["net_max_profit_usd"] = None
        result["disclaimer"] = "SYNTHETIC/ASSUMED SCENARIO; NOT VERIFIED PACKAGE FILLS OR TRADING EDGE. NEVER LIVE APPROVAL."
        return result


def _signature(leg: Leg) -> tuple[str, str, int]:
    return leg.kind, leg.side, leg.quantity


def _shape_id(s: Structure) -> str | None:
    """Strictly validate expected family, quantities, strikes and cover."""
    k = s.strategy_id
    if k not in CATALOGUE and k != LEGACY_REVERSE_ID:
        return "UNKNOWN_STRATEGY_ID"
    ls = s.legs
    if not ls or len(ls) != {"S01": 2, "S02": 2, "S03": 2, "S04": 2,
                            "S05": 3, "S06": 2, "S07": 2, "S08": 3,
                            "S09": 4, "S10": 4, "X11": 2,
                            LEGACY_REVERSE_ID: 3}[k]:
        return "WRONG_LEG_COUNT"
    options = [l for l in ls if l.kind != "STOCK"]
    stocks = [l for l in ls if l.kind == "STOCK"]
    if any(l.kind not in ("CALL", "PUT", "STOCK") or
           l.side not in ("BUY", "SELL") or
           type(l.quantity) is not int or l.quantity < 1 for l in ls):
        return "INVALID_LEG_TYPE_OR_QUANTITY"
    if not options or any(l.multiplier <= 0 or l.strike is None
                          or l.strike < 0 or not l.expiration for l in options):
        return "INVALID_OPTION_CONTRACT"
    if len({(l.expiration, l.multiplier) for l in options}) != 1:
        return "MIXED_EXPIRY_OR_MULTIPLIER"
    if stocks and (len(stocks) != 1 or stocks[0].multiplier != 1 or
                   stocks[0].strike is not None or
                   stocks[0].expiration is not None):
        return "INVALID_STOCK_LEG"
    if k in ("S01", "S02", "S05"):
        if len(stocks) != 1 or stocks[0].side != "BUY":
            return "MISSING_LONG_STOCK_COVER"
        if dec(stocks[0].quantity) != sum(
                (dec(l.quantity) * l.multiplier for l in options if l.side == "SELL"),
                Decimal(0)) and k in ("S01", "S05"):
            return "UNCOVERED_SHORT_CALL"
        if dec(stocks[0].quantity) != options[0].multiplier:
            return "STOCK_SHARE_RATIO_MISMATCH"
        if k == "S01" and [(l.kind, l.side) for l in options] != [("CALL", "SELL")]:
            return "INVALID_COVERED_CALL_SHAPE"
        if k == "S02" and [(l.kind, l.side) for l in options] != [("PUT", "BUY")]:
            return "INVALID_PROTECTIVE_PUT_SHAPE"
        if k == "S05" and (sorted((l.kind, l.side) for l in options)
                            != [("CALL", "SELL"), ("PUT", "BUY")] or
                            next(l.strike for l in options if l.kind == "PUT") >=
                            next(l.strike for l in options if l.kind == "CALL")):
            return "INVALID_COLLAR_SHAPE"
        return None
    if stocks:
        return "STOCK_NOT_ALLOWED_IN_THIS_STRATEGY"
    if k in ("S03", "S04", "X11"):
        if {l.quantity for l in options} != {1}:
            return "VERTICAL_REQUIRES_ONE_CONTRACT_PER_LEG"
        if sorted(l.side for l in options) != ["BUY", "SELL"]:
            return "VERTICAL_REQUIRES_BUY_AND_SELL"
        buy = next(l for l in options if l.side == "BUY")
        sell = next(l for l in options if l.side == "SELL")
        if buy.kind != sell.kind or buy.strike == sell.strike:
            return "INVALID_VERTICAL_CONTRACTS"
        if (k == "S03" and (buy.kind != "CALL" or buy.strike >= sell.strike)) or (
                k == "S04" and (buy.kind != "PUT" or buy.strike <= sell.strike)) or (
                k == "X11" and not (
                    (buy.kind == "CALL" and buy.strike < sell.strike) or
                    (buy.kind == "PUT" and buy.strike > sell.strike))):
            return "INVALID_DIRECTIONAL_VERTICAL"
        return None
    if k in ("S06", "S07"):
        if sorted((l.kind, l.side, l.quantity) for l in options) != [
                ("CALL", "BUY", 1), ("PUT", "BUY", 1)]:
            return "INVALID_LONG_VOL_STRUCTURE"
        p = next(l.strike for l in options if l.kind == "PUT")
        c = next(l.strike for l in options if l.kind == "CALL")
        if (k == "S06" and p != c) or (k == "S07" and p >= c):
            return "INVALID_STRADDLE_STRANGLE_STRIKES"
        return None
    if k in ("S08", LEGACY_REVERSE_ID):
        if len({l.kind for l in options}) != 1:
            return "MIXED_BUTTERFLY_RIGHTS"
        o = sorted(options, key=lambda l: l.strike)
        expected = (("BUY", 1), ("SELL", 2), ("BUY", 1)) if k == "S08" else (
            ("SELL", 1), ("BUY", 2), ("SELL", 1))
        if tuple((l.side, l.quantity) for l in o) != expected:
            return "INVALID_BUTTERFLY_SIGNS"
        if o[1].strike - o[0].strike <= 0 or (
                o[1].strike - o[0].strike != o[2].strike - o[1].strike):
            return "UNEQUAL_BUTTERFLY_WINGS"
        return None
    if k == "S09":
        o = sorted(options, key=lambda l: l.strike)
        if tuple((l.kind, l.side, l.quantity) for l in o) != (
                ("PUT", "BUY", 1), ("PUT", "SELL", 1),
                ("CALL", "SELL", 1), ("CALL", "BUY", 1)):
            return "INVALID_IRON_CONDOR_SHAPE"
        if len({l.strike for l in o}) != 4:
            return "OVERLAPPING_IRON_CONDOR_STRIKES"
        return None
    if k == "S10":
        if sorted((l.kind, l.side, l.quantity) for l in options) != [
                ("CALL", "BUY", 1), ("CALL", "SELL", 1),
                ("PUT", "BUY", 1), ("PUT", "SELL", 1)]:
            return "INVALID_IRON_BUTTERFLY_SHAPE"
        cp = {l.side: l.strike for l in options if l.kind == "CALL"}
        pp = {l.side: l.strike for l in options if l.kind == "PUT"}
        if not (pp["BUY"] < pp["SELL"] == cp["SELL"] < cp["BUY"]):
            return "INVALID_IRON_BUTTERFLY_STRIKES"
        return None
    return "INVALID_STRATEGY_FAMILY"


def _intrinsic(l: Leg, spot: Decimal) -> Decimal:
    if l.kind == "STOCK":
        return spot
    if l.kind == "CALL":
        return max(Decimal(0), spot - l.strike)
    return max(Decimal(0), l.strike - spot)


def _payoff(s: Structure, entry_cashflow: Decimal) -> tuple[Decimal, Decimal | None, tuple[Decimal, ...], bool]:
    strikes = sorted({l.strike for l in s.legs if l.strike is not None})
    knots = [Decimal(0), *strikes]
    def pnl(spot: Decimal) -> Decimal:
        return entry_cashflow + sum(
            (_intrinsic(l, spot) * l.multiplier * l.quantity
             * (1 if l.side == "BUY" else -1) for l in s.legs), Decimal(0))
    values = [pnl(k) for k in knots]
    # Determine right-tail slope analytically, NOT by a guessed huge spot.
    slope = sum((
        dec(l.quantity) * l.multiplier *
        (1 if l.side == "BUY" else -1)
        for l in s.legs if l.kind in ("STOCK", "CALL")), Decimal(0))
    if slope < 0:
        raise ValueError("UNLIMITED_THEORETICAL_LOSS")
    roots: set[Decimal] = set()
    for i in range(len(knots)-1):
        x1, x2 = knots[i], knots[i+1]
        y1, y2 = values[i], values[i+1]
        if y1 == 0:
            roots.add(x1)
        if y2 == 0:
            roots.add(x2)
        if y1*y2 < 0:
            roots.add(x1 - y1 * (x2-x1) / (y2-y1))
    if values[-1] == 0:
        roots.add(knots[-1])
    elif slope > 0 and values[-1] < 0:
        roots.add(knots[-1] - values[-1] / slope)
    return (-min(Decimal(0), *values),
            None if slope > 0 else max(values),
            tuple(sorted(roots)), min(values) > 0)


def _bad(state: str, s: Structure, *reasons: str) -> Feasibility:
    return Feasibility(s.strategy_id, state, tuple(reasons), None, None, False,
                       None, None, None, ())


def evaluate(s: Structure, policy: QuoteCostPolicy) -> Feasibility:
    """Pure evaluation; never accepts 'PASSED' as live authorization."""
    try:
        error = _shape_id(s)
    except (ValueError, TypeError, InvalidOperation) as exc:
        return _bad("FAILED_STRUCTURE", s, f"INVALID_STRUCTURE_INPUT:{exc}")
    if error:
        return _bad("FAILED_STRUCTURE", s, error)
    try:
        try:
            decision = utc(s.decision_at)
        except ValueError:
            return _bad("UNSCORABLE", s, "DECISION_TIMESTAMP_TZ_MISSING_OR_INVALID")
        if not s.signal_version:
            return _bad("FAILED_STRUCTURE", s, "MISSING_SIGNAL_VERSION")
        reasons: list[str] = []
        quote_times: list[datetime] = []
        cashflow = Decimal(0)
        for l in s.legs:
            if l.kind != "STOCK" and datetime.fromisoformat(l.expiration).date() < decision.date():
                return _bad("UNSCORABLE", s, "OPTION_EXPIRED_BEFORE_DECISION")
            if l.bid is None or l.ask is None or l.quote_at is None:
                reasons.append("MISSING_CONTEMPORANEOUS_QUOTE")
                continue
            if l.bid < 0 or l.ask < l.bid:
                return _bad("UNSCORABLE", s, "CROSSED_OR_INVALID_QUOTE")
            try:
                stamp = utc(l.quote_at)
            except ValueError:
                return _bad("UNSCORABLE", s, "QUOTE_TIMESTAMP_TZ_MISSING_OR_INVALID")
            quote_times.append(stamp)
            age = (decision - stamp).total_seconds()
            if age < 0:
                return _bad("UNSCORABLE", s, "FUTURE_QUOTE_LEAKAGE")
            if policy.max_quote_age_seconds is None:
                reasons.append("FRESHNESS_RULE_NOT_FROZEN")
            elif age > policy.max_quote_age_seconds:
                reasons.append("STALE_QUOTE")
            available = l.ask_size if l.side == "BUY" else l.bid_size
            if available is None:
                reasons.append("QUOTE_SIDE_SIZE_NOT_VERIFIED")
            elif available < l.quantity:
                reasons.append("INSUFFICIENT_VISIBLE_SIDE_SIZE")
            price = l.ask if l.side == "BUY" else l.bid
            cashflow += price * l.multiplier * l.quantity * (
                -1 if l.side == "BUY" else 1)
        if any(r in reasons for r in ("MISSING_CONTEMPORANEOUS_QUOTE",)):
            return _bad("UNSCORABLE", s, *sorted(set(reasons)))
        if policy.max_leg_quote_skew_seconds is None:
            reasons.append("QUOTE_SYNCHRONY_RULE_NOT_FROZEN")
        elif policy.max_leg_quote_skew_seconds < 0:
            return _bad("UNSCORABLE", s, "INVALID_QUOTE_SYNCHRONY_LIMIT")
        elif quote_times and (max(quote_times)-min(quote_times)).total_seconds() > policy.max_leg_quote_skew_seconds:
            reasons.append("LEGS_NOT_QUOTED_SYNCHRONOUSLY")
        if policy.fx_observed_at is None:
            reasons.append("FX_OBSERVATION_TIME_MISSING")
        elif utc(policy.fx_observed_at) > decision:
            return _bad("UNSCORABLE", s, "FUTURE_FX_RATE_LEAKAGE")
        gross_loss, max_profit, roots, apparent_arbitrage = _payoff(s, cashflow)
        if apparent_arbitrage:
            reasons.append("APPARENT_STATIC_ARBITRAGE_VERIFY_QUOTES")
        if policy.option_cost_per_contract_side_usd is None:
            reasons.append("BROKER_OPTION_COST_MISSING")
        if any(l.kind == "STOCK" for l in s.legs) and (
                policy.stock_round_trip_cost_usd is None):
            reasons.append("BROKER_STOCK_COST_MISSING")
        if policy.eur_to_usd is None or not policy.fx_provenance:
            reasons.append("FX_PROVENANCE_OR_RATE_MISSING")
        if not policy.cost_provenance:
            reasons.append("COST_PROVENANCE_MISSING")
        if policy.additional_round_trip_cost_usd is None:
            reasons.append("SLIPPAGE_AND_FX_COST_BUDGET_MISSING")
        if policy.tax_cost_usd is None:
            reasons.append("TAX_COST_ASSUMPTION_MISSING")
        if s.strategy_id in ("S01", "S02", "S05") and not policy.verified_share_inventory:
            reasons.append("OWNED_SHARE_INVENTORY_UNVERIFIED")
        fees = None
        if (policy.option_cost_per_contract_side_usd is not None and
                policy.additional_round_trip_cost_usd is not None and
                policy.tax_cost_usd is not None and
                (policy.stock_round_trip_cost_usd is not None or
                 all(l.kind != "STOCK" for l in s.legs))):
            fees = sum(
                (dec(l.quantity) * 2 * policy.option_cost_per_contract_side_usd
                 for l in s.legs if l.kind != "STOCK"), Decimal(0))
            if any(l.kind == "STOCK" for l in s.legs):
                fees += policy.stock_round_trip_cost_usd
            fees += policy.additional_round_trip_cost_usd + policy.tax_cost_usd
        capital_eur = None
        if fees is not None and policy.eur_to_usd is not None:
            # Worst terminal loss alone is insufficient: opening a debit
            # position also requires funding the up-front cash debit.
            if policy.eur_to_usd <= 0:
                return _bad("UNSCORABLE", s, "INVALID_FX_RATE")
            capital_usd = max(gross_loss, max(-cashflow, Decimal(0))) + fees
            capital_eur = (capital_usd / policy.eur_to_usd).quantize(
                CENTS, rounding=ROUND_CEILING)
            if capital_eur > policy.bankroll_eur:
                reasons.append("EXCEEDS_EUR_500_BANKROLL")
        if any(x is not None and x < 0 for x in (
                policy.option_cost_per_contract_side_usd,
                policy.stock_round_trip_cost_usd,
                policy.additional_round_trip_cost_usd,
                policy.tax_cost_usd)):
            return _bad("UNSCORABLE", s, "NEGATIVE_TRANSACTION_COST")
        if policy.max_quote_age_seconds is not None and policy.max_quote_age_seconds < 0:
            return _bad("UNSCORABLE", s, "INVALID_FRESHNESS_RULE")
        if policy.bankroll_eur != BANKROLL_EUR:
            return _bad("FAILED_STRUCTURE", s, "BANKROLL_LIMIT_MUST_EQUAL_EUR_500")
        if fees is not None and max_profit is not None and max_profit - fees <= 0:
            reasons.append("NON_POSITIVE_BEST_CASE_NET_EXPIRY_PAYOFF")
        if s.strategy_id == LEGACY_REVERSE_ID:
            state = "LEGACY_REFERENCE_ONLY"
        elif s.strategy_id in ("S01", "S02", "S05"):
            state = "REFERENCE_HEDGE_ONLY"
        elif "NON_POSITIVE_BEST_CASE_NET_EXPIRY_PAYOFF" in reasons:
            state = "ECONOMICALLY_DOMINATED_AFTER_ASSUMED_COSTS"
        elif "EXCEEDS_EUR_500_BANKROLL" in reasons:
            state = "OVER_CAP"
        elif reasons:
            state = "INSUFFICIENT_EVIDENCE"
        else:
            state = "INDICATIVELY_AFFORDABLE_NOT_EXECUTABLE"
        return Feasibility(
            s.strategy_id, state, tuple(sorted(set(reasons))),
            money(gross_loss),
            None if max_profit is None else money(max_profit),
            max_profit is None, money(cashflow),
            None if fees is None else money(fees),
            None if capital_eur is None else money(capital_eur),
            tuple(money(v) for v in roots),
            () if fees is None else tuple(money(v) for v in _payoff(s, cashflow - fees)[2]),
        )
    except (ValueError, InvalidOperation, TypeError, KeyError) as exc:
        return _bad("UNSCORABLE", s, str(exc))


def from_shadow_proposal(
    structure_json: str,
    quote_rows_by_id: Mapping[int, Mapping[str, Any]],
    *,
    decision_at: str,
    signal_version: str,
    reference: str | None = None,
    frozen_entry_pricing_json: str | None = None,
) -> Structure:
    """Adapter for migration-011 structure_json, with contemporaneous quotes.

    A frozen entry price is cross-checked against the actual bid/ask quote
    rather than being silently substituted for missing market information.
    """
    data = json.loads(structure_json)
    family = data["structure_id"]
    strategy_id = {
        "LONG_1_2_1_BUTTERFLY": "S08",
        "REVERSE_1_2_1_BUTTERFLY": LEGACY_REVERSE_ID,
    }.get(family)
    if strategy_id is None:
        raise ValueError("UNKNOWN_LEGACY_SHADOW_STRUCTURE")
    frozen = {}
    if frozen_entry_pricing_json is not None:
        entry = json.loads(frozen_entry_pricing_json)
        if entry.get("pricing_basis") != "BUY_AT_ASK_SELL_AT_BID":
            raise ValueError("UNEXPECTED_ENTRY_PRICING_CONTRACT")
        frozen = {int(x["option_quote_id"]): dec(x["entry_price"])
                  for x in entry["legs"]}
    legs = []
    snapshot_ids: set[int] = set()
    for item in data["legs"]:
        qid = int(item["option_quote_id"])
        q = quote_rows_by_id.get(qid)
        if q is None:
            raise ValueError(f"LEG_QUOTE_NOT_IN_FROZEN_INPUT:{qid}")
        if q.get("snapshot_id") is None or q.get("right") is None or q.get("strike") is None:
            raise ValueError("QUOTE_CONTRACT_IDENTITY_OR_SNAPSHOT_MISSING")
        snapshot_ids.add(int(q["snapshot_id"]))
        side = item["side"]
        right = item["right"]
        if side not in ("BUY", "SELL") or right not in ("C", "P"):
            raise ValueError("INVALID_LEG_RIGHT_OR_SIDE")
        b = None if q.get("bid") is None else dec(q["bid"])
        a = None if q.get("ask") is None else dec(q["ask"])
        price = a if side == "BUY" else b
        if str(q.get("right", right)) != right or (
                q.get("strike") is not None and dec(q["strike"]) != dec(item["strike"])):
            raise ValueError("QUOTE_CONTRACT_IDENTITY_MISMATCH")
        if qid in frozen and (price is None or price != frozen[qid]):
            raise ValueError("FROZEN_ENTRY_DIFFERS_FROM_SOURCE_QUOTE")
        legs.append(Leg(
            kind="CALL" if right == "C" else "PUT",
            side=side, quantity=int(item["quantity"]),
            multiplier=dec(item["shares_per_contract"]),
            strike=dec(item["strike"]), expiration=str(q["expiration"]),
            bid=b, ask=a, quote_at=q.get("quote_at"),
            bid_size=None if q.get("bid_size") is None else dec(q["bid_size"]),
            ask_size=None if q.get("ask_size") is None else dec(q["ask_size"]),
            source_id=str(qid),
        ))
    if len(snapshot_ids) != 1:
        raise ValueError("MULTI_SNAPSHOT_ENTRY_IS_NOT_SNAPSHOT_COHERENT")
    return Structure(strategy_id, signal_version, decision_at, tuple(legs), reference)


def catalogue_without_quotes() -> list[dict[str, str]]:
    """All eleven taxonomy rows remain untested until source data are supplied."""
    return [
        {"strategy_id": k, "name": name, "lane": lane,
         "status": "UNTESTED_NO_QUOTE_OR_OUTCOME_EVIDENCE"}
        for k, (name, lane) in CATALOGUE.items()
    ]
