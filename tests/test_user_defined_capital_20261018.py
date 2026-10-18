"""User-entered capital replaces every active fixed 500-euro wallet gate.

Prior 500-euro policies in historical data remain untouched.
"""
from dataclasses import replace
from decimal import Decimal

import pytest

from src.decision.desk import build_risk_plan
from src.research.strategy_falsification_v1 import evaluate
from tests.test_decision_desk_v1 import _candidate
from tests.test_strategy_falsification_v1 import POLICY, examples


def test_decision_desk_accepts_user_selected_capital_above_500_eur():
    plan = build_risk_plan(
        _candidate(reserved_risk_eur_minor=120_000),
        max_trade_risk_eur=1_500.0,
        stop_loss_fraction=0.25,
        bankroll_eur=10_000.0,
    )
    assert plan.configured
    assert plan.state == "RISK_POLICY_PASS"
    assert plan.bankroll_fraction == pytest.approx(0.12)
    assert plan.planned_loss_trigger_eur == pytest.approx(300.0)


@pytest.mark.parametrize("capital", [None, 0.0, -2.0, float("nan"), float("inf")])
def test_decision_desk_never_assumes_capital_when_missing_or_invalid(capital):
    plan = build_risk_plan(
        _candidate(),
        max_trade_risk_eur=40.0,
        stop_loss_fraction=0.50,
        bankroll_eur=capital,
    )
    assert not plan.configured
    assert not plan.passes_risk_budget


def test_loss_budget_still_cannot_exceed_user_allocation():
    plan = build_risk_plan(
        _candidate(),
        max_trade_risk_eur=1_200.0,
        stop_loss_fraction=0.50,
        bankroll_eur=750.0,
    )
    assert not plan.configured


def test_stage0_simulator_uses_user_allocation_and_never_overrides_it():
    structure = examples()["S01"]  # Reference-only covered call: capital-intensive
    five_hundred = evaluate(
        structure, replace(POLICY, bankroll_eur=Decimal("500"))
    )
    twelve_thousand = evaluate(
        structure, replace(POLICY, bankroll_eur=Decimal("12000"))
    )
    assert "EXCEEDS_ALLOCATED_CAPITAL" in five_hundred.reasons
    assert "EXCEEDS_ALLOCATED_CAPITAL" not in twelve_thousand.reasons
    assert twelve_thousand.state == "REFERENCE_HEDGE_ONLY"
    assert "OWNED_SHARE_INVENTORY_UNVERIFIED" in twelve_thousand.reasons


@pytest.mark.parametrize("capital", [None, Decimal("0"), Decimal("-1"), Decimal("NaN")])
def test_stage0_missing_or_invalid_capital_is_never_assumed(capital):
    result = evaluate(
        examples()["S03"],
        replace(POLICY, bankroll_eur=capital),
    )
    assert result.state == "UNSCORABLE"
    assert "CAPITAL_ALLOCATION_NOT_CONFIGURED" in result.reasons
