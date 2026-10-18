"""Manual execution is a reviewed preview, never a broker-side order."""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from src.decision.manual_trade_review import manual_trade_review
from src.decision.opportunity import VERDICT_MARGINAL, VERDICT_WORTH, assess_idea
from src.decision.trade_ideas import load_current_ideas
from tests.test_trade_ideas import seed_scenario


NOW = datetime(2026, 10, 19, 15, 0, tzinfo=UTC)


def _fixture(db_path):
    seed_scenario(db_path, with_v2=True)
    ideas, errors, _ = load_current_ideas(db_path=db_path)
    assert not errors and ideas
    idea = replace(
        ideas[0], admission_decision="ADMITTED", as_of="2026-10-19T14:59:30Z",
        max_loss_usd=20.0,
    )
    assessment = replace(assess_idea(idea), verdict=VERDICT_WORTH)
    symbols = {leg.option_quote_id: f"TEST_CALL_{leg.strike:g}" for leg in idea.legs}
    return idea, assessment, symbols


def _review(idea, assessment, symbols, **overrides):
    args = dict(
        now=NOW, contract_symbols_by_quote_id=symbols,
        leg_quote_at_by_quote_id={qid: '2026-10-19T14:59:30Z' for qid in symbols},
        available_cash_eur=500.0, current_open_risk_eur=0.0,
        eur_to_usd=1.1, broker_prices_and_fees_confirmed=True,
        current_positions_confirmed=True,
    )
    args.update(overrides)
    return manual_trade_review(idea, assessment, **args)


def test_manual_ticket_can_pass_for_recent_confirmed_small_risk_while_never_ordering(db_path):
    idea, a, symbols = _fixture(db_path)
    review = _review(idea, a, symbols)
    assert review.ready_for_manual_broker_requote
    assert review.broker_order_submitted is False
    assert review.reasons == ()
    assert review.conservative_risk_eur is not None
    assert review.conservative_risk_eur <= 50
    assert len(review.legs) == len(idea.legs)


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"now": datetime(2026, 10, 18, 15, tzinfo=UTC)}, "US_OPTIONS_MARKET_CLOSED"),
        ({"now": datetime(2026, 10, 19, 15, 5, tzinfo=UTC)}, "QUOTE_EXPIRED_RECHECK_BROKER"),
        ({"eur_to_usd": None}, "NO_VERIFIED_EURUSD_RATE"),
        ({"broker_prices_and_fees_confirmed": False}, "BROKER_PRICES_FEES_NOT_CONFIRMED"),
        ({"current_positions_confirmed": False}, "EXISTING_POSITION_RISK_NOT_CONFIRMED"),
        ({"current_open_risk_eur": 490}, "TRADE_EXCEEDS_REMAINING_BANKROLL"),
        ({"available_cash_eur": 100.0}, "TRADE_EXCEEDS_TEN_PERCENT_CAP"),
        ({"contract_symbols_by_quote_id": {}}, "MISSING_EXACT_OPTION_CONTRACT_SYMBOL"),
        ({"leg_quote_at_by_quote_id": {}}, "MISSING_LEG_BID_ASK_TIMESTAMP"),
    ],
)
def test_manual_ticket_fails_closed(db_path, change, reason):
    idea, a, symbols = _fixture(db_path)
    review = _review(idea, a, symbols, **change)
    assert not review.ready_for_manual_broker_requote
    assert reason in review.reasons
    assert review.broker_order_submitted is False


def test_uncalibrated_opportunity_never_ready_for_manual_requote(db_path):
    idea, a, symbols = _fixture(db_path)
    a = replace(a, verdict=VERDICT_MARGINAL)
    review = _review(idea, a, symbols)
    assert not review.ready_for_manual_broker_requote
    assert "OPPORTUNITY_NOT_INDEPENDENTLY_CONFIRMED" in review.reasons


def test_nans_and_naive_times_are_not_accepted(db_path):
    idea, a, symbols = _fixture(db_path)
    with pytest.raises(ValueError, match="finite"):
        _review(idea, a, symbols, available_cash_eur=float("nan"))
    with pytest.raises(ValueError, match="timezone"):
        _review(idea, a, symbols, now=datetime(2026, 10, 19, 15, 0))


@pytest.mark.parametrize(
    "allocated_eur,expected_single_trade_limit_eur",
    [(750.0, 75.0), (2_500.0, 250.0), (10_000.0, 1_000.0)],
)
def test_user_allocated_capital_is_not_clamped_to_500_eur(
    db_path, allocated_eur, expected_single_trade_limit_eur
):
    idea, assessment, symbols = _fixture(db_path)
    review = _review(
        idea, assessment, symbols, available_cash_eur=allocated_eur
    )
    assert review.ready_for_manual_broker_requote
    assert review.max_risk_per_trade_eur == pytest.approx(expected_single_trade_limit_eur)
    assert review.available_capital_eur == pytest.approx(allocated_eur)
    assert review.broker_order_submitted is False


def test_larger_user_allocation_may_support_larger_defined_risk(db_path):
    idea, assessment, symbols = _fixture(db_path)
    larger_idea = replace(idea, max_loss_usd=650.0)
    small = _review(
        larger_idea, assessment, symbols, available_cash_eur=500.0
    )
    larger = _review(
        larger_idea, assessment, symbols, available_cash_eur=10_000.0
    )
    assert "TRADE_EXCEEDS_TEN_PERCENT_CAP" in small.reasons
    assert larger.ready_for_manual_broker_requote
    assert larger.max_risk_per_trade_eur == pytest.approx(1_000.0)
    assert larger.conservative_risk_eur > 500.0


def test_user_allocated_capital_must_remain_nonnegative_and_finite(db_path):
    idea, assessment, symbols = _fixture(db_path)
    for allocation in (float("inf"), float("-inf"), -1.0):
        with pytest.raises(ValueError, match="finite|negative"):
            _review(idea, assessment, symbols, available_cash_eur=allocation)
