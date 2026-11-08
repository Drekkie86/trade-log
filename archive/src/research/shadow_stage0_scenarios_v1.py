"""Hypothetical Stage-0 strategy presets; no real market data or orders.

Every premium, timestamp, FX rate and source depth is an explicit SYNTHETIC
SCENARIO ASSUMPTION. Never record these fixtures as historical observations,
approved strategies, live entitlements or independently qualified outcomes.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from src.research.strategy_falsification_v1 import (
    CATALOGUE, Leg, Structure, QuoteCostPolicy,
)

D = Decimal

# Each option: right, entry side, strike, indicative bid, indicative ask, qty.
# Stock: STOCK, BUY, nominal zero strike, synthetic bid/ask, shares.
_PRESETS = {
    "S01": (("STOCK", "BUY", 0, "99", "100", 100),
            ("CALL", "SELL", 105, "3", "4", 1)),
    "S02": (("STOCK", "BUY", 0, "99", "100", 100),
            ("PUT", "BUY", 95, "1", "2", 1)),
    "S03": (("CALL", "BUY", 100, "5", "6", 1),
            ("CALL", "SELL", 105, "3", "4", 1)),
    "S04": (("PUT", "BUY", 105, "5", "6", 1),
            ("PUT", "SELL", 100, "3", "4", 1)),
    "S05": (("STOCK", "BUY", 0, "99", "100", 100),
            ("PUT", "BUY", 95, "1", "2", 1),
            ("CALL", "SELL", 105, "3", "4", 1)),
    "S06": (("CALL", "BUY", 100, "4", "5", 1),
            ("PUT", "BUY", 100, "3", "4", 1)),
    "S07": (("PUT", "BUY", 95, "1", "2", 1),
            ("CALL", "BUY", 105, "2", "3", 1)),
    "S08": (("CALL", "BUY", 95, "7", "8", 1),
            ("CALL", "SELL", 100, "5", "6", 2),
            ("CALL", "BUY", 105, "2", "3", 1)),
    "S09": (("PUT", "BUY", 90, "0.5", "1", 1),
            ("PUT", "SELL", 95, "2", "2.5", 1),
            ("CALL", "SELL", 105, "2", "2.5", 1),
            ("CALL", "BUY", 110, "0.5", "1", 1)),
    "S10": (("PUT", "BUY", 95, "1.5", "2", 1),
            ("PUT", "SELL", 100, "3", "4", 1),
            ("CALL", "SELL", 100, "3", "4", 1),
            ("CALL", "BUY", 105, "1.5", "2", 1)),
    "X11": (("CALL", "BUY", 100, "5", "6", 1),
            ("CALL", "SELL", 105, "3", "4", 1)),
}


def hypothetical_scenario(strategy_id: str, *, decision_time: datetime | None = None):
    """Build a fresh-looking-but-fictional as-of scenario with no source identity."""
    if strategy_id not in CATALOGUE:
        raise ValueError("UNKNOWN_STRATEGY_FAMILY")
    decision = decision_time or datetime.now(timezone.utc)
    if decision.tzinfo is None or decision.utcoffset() is None:
        raise ValueError("SCENARIO_DECISION_TIMESTAMP_MUST_BE_AWARE")
    decision = decision.astimezone(timezone.utc)
    quote_at = (decision - timedelta(seconds=2)).isoformat()
    expires = (decision + timedelta(days=35)).date().isoformat()
    legs = []
    for right, side, strike, bid, ask, quantity in _PRESETS[strategy_id]:
        stock = right == "STOCK"
        legs.append(Leg(
            kind=right, side=side, quantity=quantity,
            multiplier=D("1") if stock else D("100"),
            strike=None if stock else D(str(strike)),
            expiration=None if stock else expires,
            bid=D(bid), ask=D(ask), quote_at=quote_at,
            bid_size=D("1000") if stock else D("20"),
            ask_size=D("1000") if stock else D("20"),
            source_id="SYNTHETIC_NOT_A_MARKET_RECORD",
        ))
    structure = Structure(
        strategy_id=strategy_id, signal_version="SYNTHETIC_STAGE0_NO_SIGNAL",
        decision_at=decision.isoformat(), legs=tuple(legs),
        reference="MANUALLY_ADJUSTABLE_SYNTHETIC_SCENARIO_NOT_A_REAL_QUOTE",
    )
    policy = QuoteCostPolicy(
        option_cost_per_contract_side_usd=D("3"),
        stock_round_trip_cost_usd=D("2"),
        eur_to_usd=D("1.10"),
        cost_provenance="USER_ASSUMPTION_NOT_ACTUAL_BROKER_FEES",
        fx_provenance="USER_ASSUMPTION_NOT_ACTUAL_FX",
        max_quote_age_seconds=15,
        verified_share_inventory=False,
        bankroll_eur=None,  # Stage-0 UI requires explicit capital choice
        max_leg_quote_skew_seconds=15,
        additional_round_trip_cost_usd=D("1"),
        tax_cost_usd=D("1"),
        fx_observed_at=quote_at,
    )
    return structure, policy
