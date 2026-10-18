"""Manual live-order review: bounded risk, real quote freshness, no broker submission.

This does not send an order. It creates a precise indicative leg checklist
that must be re-quoted and submitted manually in the user's own broker.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Mapping

import exchange_calendars as xcals
import pandas as pd

from src.decision.opportunity import OpportunityAssessment, VERDICT_WORTH
from src.decision.trade_ideas import TradeIdea, structure_fees_usd

MAX_BANKROLL_EUR = 500.0
MAX_SINGLE_TRADE_FRACTION = 0.10
MAX_QUOTE_AGE_SECONDS = 120
_NYSE = xcals.get_calendar("XNYS")


@dataclass(frozen=True)
class ManualLeg:
    contract_symbol: str
    action: str
    quantity: int
    right: str
    strike: float
    estimated_entry_per_share_usd: float


@dataclass(frozen=True)
class ManualTradeReview:
    ready_for_manual_broker_requote: bool
    reasons: tuple[str, ...]
    legs: tuple[ManualLeg, ...]
    conservative_risk_eur: float | None
    max_risk_per_trade_eur: float
    available_capital_eur: float
    as_of: str | None
    broker_order_submitted: bool = False


def _instant(value: object) -> datetime | None:
    try:
        t = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return t.astimezone(UTC) if t.tzinfo is not None else None
    except (ValueError, TypeError, OverflowError):
        return None


def manual_trade_review(
    idea: TradeIdea,
    assessment: OpportunityAssessment,
    *,
    now: datetime,
    contract_symbols_by_quote_id: Mapping[int, str],
    leg_quote_at_by_quote_id: Mapping[int, str],
    available_cash_eur: float,
    current_open_risk_eur: float,
    eur_to_usd: float | None,
    broker_prices_and_fees_confirmed: bool,
    current_positions_confirmed: bool,
) -> ManualTradeReview:
    """Only a review checklist, never a broker permission or trade order."""
    if now.tzinfo is None:
        raise ValueError("Current time needs an explicit timezone.")
    now = now.astimezone(UTC)
    reasons: list[str] = []
    if not math.isfinite(float(available_cash_eur)) or not math.isfinite(float(current_open_risk_eur)):
        raise ValueError("Cash and existing risk must be finite.")
    if available_cash_eur < 0 or current_open_risk_eur < 0:
        raise ValueError("Cash and existing risk cannot be negative.")
    bankroll = min(MAX_BANKROLL_EUR, float(available_cash_eur))
    exposure = float(current_open_risk_eur)
    single_cap = bankroll * MAX_SINGLE_TRADE_FRACTION
    available = max(0.0, bankroll - exposure)

    if not _NYSE.is_open_on_minute(pd.Timestamp(now)):
        reasons.append("US_OPTIONS_MARKET_CLOSED")
    snapshot = _instant(idea.as_of)
    if snapshot is None:
        reasons.append("MISSING_TIMEZONE_AWARE_QUOTE_TIMESTAMP")
    else:
        seconds = (now - snapshot).total_seconds()
        if seconds < 0 or seconds > MAX_QUOTE_AGE_SECONDS:
            reasons.append("QUOTE_EXPIRED_RECHECK_BROKER")
    if idea.admission_decision != "ADMITTED":
        reasons.append("NOT_AN_ADMITTED_SHADOW_CANDIDATE")
    if assessment.verdict != VERDICT_WORTH:
        reasons.append("OPPORTUNITY_NOT_INDEPENDENTLY_CONFIRMED")
    if not broker_prices_and_fees_confirmed:
        reasons.append("BROKER_PRICES_FEES_NOT_CONFIRMED")
    if not current_positions_confirmed:
        reasons.append("EXISTING_POSITION_RISK_NOT_CONFIRMED")

    if eur_to_usd is None or not math.isfinite(eur_to_usd) or eur_to_usd <= 0:
        reasons.append("NO_VERIFIED_EURUSD_RATE")
        risk_eur = None
    elif idea.max_loss_usd is None or not math.isfinite(idea.max_loss_usd) or idea.max_loss_usd <= 0:
        reasons.append("NO_VALID_DEFINED_MAX_LOSS")
        risk_eur = None
    else:
        # Add the modeled commissions conservatively even if the package's
        # payoff max-loss projection already included a fee allowance.
        risk_eur = (idea.max_loss_usd + structure_fees_usd(idea.legs)) / eur_to_usd
        if risk_eur > single_cap:
            reasons.append("TRADE_EXCEEDS_TEN_PERCENT_CAP")
        if risk_eur > available:
            reasons.append("TRADE_EXCEEDS_REMAINING_BANKROLL")

    legs: list[ManualLeg] = []
    for leg in idea.legs:
        symbol = contract_symbols_by_quote_id.get(leg.option_quote_id, "")
        if not symbol:
            reasons.append("MISSING_EXACT_OPTION_CONTRACT_SYMBOL")
        leg_quote_at = _instant(leg_quote_at_by_quote_id.get(leg.option_quote_id))
        if leg_quote_at is None:
            reasons.append("MISSING_LEG_BID_ASK_TIMESTAMP")
        elif (now - leg_quote_at).total_seconds() < 0 or (
            (now - leg_quote_at).total_seconds() > MAX_QUOTE_AGE_SECONDS
        ):
            reasons.append("STALE_OPTION_LEG_BID_ASK")
        if leg.side not in ("BUY", "SELL") or leg.quantity < 1:
            reasons.append("INVALID_OPTION_LEG")
        legs.append(ManualLeg(
            contract_symbol=symbol,
            action=leg.side,
            quantity=leg.quantity,
            right=leg.right,
            strike=leg.strike,
            estimated_entry_per_share_usd=leg.ask if leg.side == "BUY" else leg.bid,
        ))

    if not idea.legs:
        reasons.append("NO_OPTION_LEGS")
    return ManualTradeReview(
        ready_for_manual_broker_requote=not reasons,
        reasons=tuple(dict.fromkeys(reasons)),
        legs=tuple(legs),
        conservative_risk_eur=risk_eur,
        max_risk_per_trade_eur=single_cap,
        available_capital_eur=available,
        as_of=idea.as_of,
    )
