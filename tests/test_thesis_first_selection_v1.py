"""One evidence contract regardless of strategy or Casino/Main risk envelope."""
from dataclasses import replace
from decimal import Decimal as D

from src.decision.thesis_first_selection_v1 import (
    EXPIRY_EXIT, FrozenThesis, SHADOW_ONLY, TerminalScenario,
    evaluate_candidate, NO_TRADE,
)
from src.research.strategy_falsification_v1 import (
    Leg, QuoteCostPolicy, Structure,
)

CUT = "2026-10-19T15:00:00Z"
QTIME = "2026-10-19T14:59:56Z"


def policy(cap="500"):
    return QuoteCostPolicy(
        option_cost_per_contract_side_usd=D("1"),
        stock_round_trip_cost_usd=None, eur_to_usd=D("1.2"),
        cost_provenance="TEST_ASSUMED_FEES_NOT_BROKER",
        fx_provenance="TEST_ASOF_FX",
        max_quote_age_seconds=15,
        bankroll_eur=D(cap), max_leg_quote_skew_seconds=15,
        additional_round_trip_cost_usd=D("1"),
        tax_cost_usd=D("1"), fx_observed_at=QTIME,
    )


def vertical():
    return Structure(
        strategy_id="S03", signal_version="TEST_UNAPPROVED",
        decision_at=CUT, reference="test:snapshot:22",
        legs=(
            Leg("CALL", "BUY", 1, D("100"), D("100"), "2026-10-23",
                D("4.9"), D("5"), QTIME, D("10"), D("10"), "1"),
            Leg("CALL", "SELL", 1, D("100"), D("105"), "2026-10-23",
                D("3"), D("3.1"), QTIME, D("10"), D("10"), "2"),
        ),
    )


def thesis():
    return FrozenThesis(
        thesis_id="PRECOMMITTED_UP_001",
        family="DIRECTIONAL_UP", frozen_at=QTIME,
        underlying="ABC", expiration="2026-10-23",
        forecast_model_version="MODEL_PREDECLARED_1",
        forecast_source="SOURCE_WITH_FROZEN_VALIDATION",
        training_cutoff="2026-10-18T15:00:00Z",
        exit_rule=EXPIRY_EXIT,
        scenarios=(
            TerminalScenario(D("100"), D("0.3")),
            TerminalScenario(D("110"), D("0.7")),
        ),
        prospective_independent_dates=20,
        matched_placebo_ci_lower_usd=D("2"),
    )


def decide(structure=None, p=None, t=None):
    return evaluate_candidate(
        structure or vertical(), p or policy(), t,
        underlying="ABC", expiration="2026-10-23",
    )


def test_unproven_thesis_is_no_trade_not_a_mathematical_approval():
    result = decide(t=None)
    assert result.state == NO_TRADE
    assert "NO_PRECOMMITTED_PREDICTIVE_THESIS" in result.blockers
    assert result.hypothetical_net_ev_usd is None
    assert not result.eligible_for_live_trading


def test_scenario_ev_is_net_of_entry_crossing_and_round_trip_costs():
    result = decide(t=thesis())
    assert result.hypothetical_net_ev_usd == D("144")
    assert result.state == SHADOW_ONLY
    assert result.authority == "NONE"
    assert not result.eligible_for_live_trading


def test_passing_distribution_without_prospective_control_is_no_trade():
    t = replace(thesis(), prospective_independent_dates=2,
                matched_placebo_ci_lower_usd=None)
    result = decide(t=t)
    assert result.hypothetical_net_ev_usd == D("144")
    assert result.state == NO_TRADE
    assert "INSUFFICIENT_INDEPENDENT_PROSPECTIVE_DATES" in result.blockers
    assert "POSITIVE_MATCHED_CONTROL_EXCESS_NOT_ESTABLISHED" in result.blockers


def test_outcome_leakage_and_forecast_training_leakage_are_blocking():
    t = replace(thesis(), frozen_at="2026-10-20T15:00:00Z",
                training_cutoff="2026-10-21T15:00:00Z")
    result = decide(t=t)
    assert "THESIS_FROZEN_AFTER_ENTRY_DECISION" in result.blockers
    assert "FORECAST_TRAINING_LEAKAGE" in result.blockers


def test_identity_and_thesis_types_cannot_be_borrowed():
    t = replace(thesis(), underlying="OTHER", family="UNAPPROVED_STRATEGY")
    result = decide(t=t)
    assert "THESIS_CONTRACT_IDENTITY_MISMATCH" in result.blockers
    assert "UNRECOGNIZED_PREDICTIVE_THESIS" in result.blockers


def test_early_exit_thesis_cannot_be_faked_using_expiry_payoff():
    result = decide(t=replace(thesis(), exit_rule="SELL_ON_IV_CONVERGENCE"))
    assert result.hypothetical_net_ev_usd is None
    assert "EXIT_PATH_PAYOFF_MODEL_NOT_AVAILABLE" in result.blockers


def test_invalid_probabilities_and_nonpositive_scenario_return_fail_closed():
    t = replace(thesis(), scenarios=(
        TerminalScenario(D("110"), D("0.6")),
        TerminalScenario(D("100"), D("0.6")),
    ))
    result = decide(t=t)
    assert "VALID_FORECAST_DISTRIBUTION_MISSING" in result.blockers
    assert result.hypothetical_net_ev_usd is None
    adverse = replace(thesis(), scenarios=(TerminalScenario(D("99"), D("1")),))
    result2 = decide(t=adverse)
    assert result2.hypothetical_net_ev_usd < 0
    assert "NON_POSITIVE_MODELED_NET_EXPECTANCY" in result2.blockers


def test_cap_and_missing_broker_receipts_block_all_namespaces():
    t = thesis()
    for cap in ("10", "100"):
        result = decide(t=t, p=policy(cap))
        assert result.state == NO_TRADE
        assert "PACKAGE_FEASIBILITY_NOT_FULLY_EVIDENCED" in result.blockers


def test_stale_option_leg_does_not_gain_authority_from_valid_forecast():
    s = vertical()
    late = replace(s.legs[0], quote_at="2026-10-19T14:59:00Z")
    result = decide(structure=replace(s, legs=(late, s.legs[1])), t=thesis())
    assert result.state == NO_TRADE
    assert "STALE_QUOTE" in result.blockers
