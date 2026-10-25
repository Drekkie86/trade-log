from dataclasses import replace
from decimal import Decimal as D

import pytest

from src.decision.thesis_first_selection_v1 import (
    EXPIRY_EXIT, FrozenThesis, TerminalScenario,
)
from src.decision.unified_trade_ranker_v1 import (
    MANUAL_REQUOTE, NO_TRADE, ModelInput, OptionCandidate,
    rank_market_opportunities,
)
from src.research.strategy_falsification_v1 import (
    Leg, QuoteCostPolicy, Structure,
)

CUT = "2026-10-19T15:00:00Z"
QUOTE = "2026-10-19T14:59:55Z"
EXPIRY = "2026-10-23"


def policy():
    return QuoteCostPolicy(
        option_cost_per_contract_side_usd=D("1"),
        stock_round_trip_cost_usd=None,
        eur_to_usd=D("1.2"), cost_provenance="TEST_ASSUMED_NOT_BROKER",
        fx_provenance="TEST_PRIOR_ECB",
        max_quote_age_seconds=15, max_leg_quote_skew_seconds=15,
        bankroll_eur=D("500"), additional_round_trip_cost_usd=D("1"),
        tax_cost_usd=D("1"), fx_observed_at=QUOTE,
    )


def leg(kind, side, strike, bid, ask, source):
    return Leg(kind, side, 1, D("100"), D(str(strike)), EXPIRY,
               D(str(bid)), D(str(ask)), QUOTE, D("10"), D("10"), source)


def structures():
    directional = Structure(
        "S03", "PRECOMMITTED_TEST", CUT,
        (leg("CALL", "BUY", 100, 4.9, 5, "c100"),
         leg("CALL", "SELL", 105, 3, 3.1, "c105")),
        "snapshot:88:XYZ:2026-10-23:S03",
    )
    volatility = Structure(
        "S06", "PRECOMMITTED_TEST", CUT,
        (leg("PUT", "BUY", 100, .9, 1, "p100"),
         leg("CALL", "BUY", 100, .9, 1, "c100")),
        "snapshot:88:XYZ:2026-10-23:S06",
    )
    return directional, volatility


def thesis(family, label, up_prob=D(".7")):
    return FrozenThesis(
        thesis_id=label, family=family, frozen_at=QUOTE,
        underlying="XYZ", expiration=EXPIRY,
        forecast_model_version=f"TEST_{label}_FROZEN",
        forecast_source=f"TEST_INDEPENDENT_{label}",
        training_cutoff="2026-10-18T15:00:00Z",
        exit_rule=EXPIRY_EXIT,
        scenarios=(
            TerminalScenario(D("100"), 1-up_prob),
            TerminalScenario(D("110"), up_prob),
        ),
        prospective_independent_dates=20,
        matched_placebo_ci_lower_usd=D("1"),
    )


def candidate(structure, family, probs=(D(".7"), D(".8"))):
    views = tuple(
        ModelInput(f"model{i}", f"independent_group{i}",
                   thesis(family, f"model{i}", prob))
        for i, prob in enumerate(probs)
    )
    return OptionCandidate(
        88, "XYZ", EXPIRY, structure, policy(), views
    )


def test_one_ranked_market_compares_different_option_strategies():
    vertical, straddle = structures()
    desk = rank_market_opportunities([
        candidate(vertical, "DIRECTIONAL_UP"),
        candidate(straddle, "LONG_VOLATILITY"),
    ])
    assert desk.state == MANUAL_REQUOTE
    assert desk.provisional_count == 2
    assert desk.rejected_count == 0
    assert desk.top.strategy_id == "S06"
    assert desk.opportunities[0].risk_adjusted_score > (
        desk.opportunities[1].risk_adjusted_score
    )
    assert desk.opportunities[0].rank == 1
    assert desk.opportunities[1].rank == 2
    assert not desk.broker_order_authority
    assert not desk.top.broker_order_authority


def test_correlated_smile_fits_are_not_three_independent_votes():
    s, _ = structures()
    shared = candidate(s, "DIRECTIONAL_UP")
    models = tuple(
        replace(x, dependence_group="SAME_THETADATA_OPTION_SURFACE")
        for x in shared.model_inputs
    )
    desk = rank_market_opportunities([replace(shared, model_inputs=models)])
    assert desk.state == NO_TRADE
    assert desk.rejected_count == 1
    assert desk.top is None
    assert desk.opportunities[0].confirming_model_groups == 1
    assert "TOO_FEW_DISTINCT_INFORMATION_GROUPS" in (
        desk.opportunities[0].missing_evidence
    )


def test_dissenting_forecast_discredits_not_outvoted_by_positive_model():
    s, _ = structures()
    disagreement = candidate(s, "DIRECTIONAL_UP", (D(".9"), D(".05")))
    out = rank_market_opportunities([disagreement])
    assert out.state == NO_TRADE
    assert out.opportunities[0].opposing_model_groups == 1
    assert "INDEPENDENT_MODEL_DISAGREES_ON_POSITIVE_EV" in (
        out.opportunities[0].missing_evidence
    )


def test_positive_model_only_forecasts_cannot_be_promoted():
    s, _ = structures()
    item = candidate(s, "DIRECTIONAL_UP")
    views = tuple(replace(m, thesis=replace(
        m.thesis,
        matched_placebo_ci_lower_usd=None,
        prospective_independent_dates=0,
    )) for m in item.model_inputs)
    out = rank_market_opportunities([replace(item, model_inputs=views)])
    assert out.state == NO_TRADE
    assert out.provisional_count == 0
    assert "POSITIVE_MATCHED_CONTROL_EXCESS_NOT_ESTABLISHED" in (
        out.opportunities[0].missing_evidence
    )


def test_no_models_or_no_broker_costs_leads_to_no_trade():
    s, _ = structures()
    item = candidate(s, "DIRECTIONAL_UP")
    empty = rank_market_opportunities([replace(item, model_inputs=())])
    assert empty.state == NO_TRADE
    assert "NO_INDEPENDENT_FORECAST_MODELS" in (
        empty.opportunities[0].missing_evidence
    )
    missing = rank_market_opportunities([replace(
        item, cost_policy=replace(policy(), tax_cost_usd=None),
    )])
    assert missing.state == NO_TRADE


def test_malformed_inputs_cannot_make_unbounded_or_repeated_rankings():
    s, _ = structures()
    one = candidate(s, "DIRECTIONAL_UP")
    with pytest.raises(ValueError, match="DUPLICATED_FROZEN_OPTION_CANDIDATE"):
        rank_market_opportunities([one, one])
    with pytest.raises(ValueError, match="EXCEEDS_BOUNDED"):
        rank_market_opportunities([one] * 201)


def test_better_theoretical_ev_cannot_override_outcome_leakage():
    s, _ = structures()
    item = candidate(s, "DIRECTIONAL_UP")
    later = tuple(replace(m, thesis=replace(
        m.thesis, frozen_at="2026-10-20T15:00:00Z",
    )) for m in item.model_inputs)
    desk = rank_market_opportunities([replace(item, model_inputs=later)])
    assert desk.state == NO_TRADE
    assert "THESIS_FROZEN_AFTER_ENTRY_DECISION" in (
        desk.opportunities[0].missing_evidence
    )


def test_zero_trade_cases_report_honestly():
    result = rank_market_opportunities([])
    assert result.state == NO_TRADE
    assert result.top is None
    assert result.rejected_count == 0
    assert result.opportunities == ()
