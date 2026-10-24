"""Complete, one-call options decision uses one price forecast for every payoff."""
from dataclasses import replace
from decimal import Decimal as D

from src.decision.thesis_first_selection_v1 import (
    FrozenThesis, TerminalScenario,
)
from src.decision.unified_trade_ranker_v1 import ModelInput, NO_TRADE
from src.decision.unified_trade_desk_v1 import evaluate_market
from src.research.independent_family_discovery_v1 import FrozenChain, FrozenQuote
from src.research.massive_underlying_observation_v1 import STOCK_PRICE_SOURCE
from src.research.strategy_falsification_v1 import QuoteCostPolicy

CUT = "2026-10-19T15:00:00Z"
SOURCE = "2026-10-19T14:59:55Z"


def chain():
    quotes = []
    for kind in ("C", "P"):
        for k in (90, 95, 100, 105, 110):
            quotes.append(FrozenQuote(
                source_id=len(quotes)+1, snapshot_id=55, expiration="2026-10-23",
                right=kind, strike=D(k), bid=D("1"), ask=D("1.1"),
                quote_at=SOURCE, reference_multiplier=D("100"),
                bid_size=D("10"), ask_size=D("10"),
            ))
    return FrozenChain(
        55, "XYZ", CUT, D("100"), STOCK_PRICE_SOURCE, SOURCE, tuple(quotes),
    )


def policy():
    return QuoteCostPolicy(
        option_cost_per_contract_side_usd=D("1"),
        stock_round_trip_cost_usd=None, eur_to_usd=D("1.2"),
        cost_provenance="SAXO_TEST_ASSUMPTION",
        fx_provenance="ECB_TEST_ASOF", max_quote_age_seconds=15,
        max_leg_quote_skew_seconds=15,
        bankroll_eur=D("500"), additional_round_trip_cost_usd=D("1"),
        tax_cost_usd=D("1"), fx_observed_at=SOURCE,
    )


def models():
    def thesis(n):
        return FrozenThesis(
            thesis_id=f"PREDECLARED_{n}",
            family="DIRECTIONAL_UP", frozen_at=SOURCE,
            underlying="XYZ", expiration="2026-10-23",
            forecast_model_version=f"FROZEN_{n}",
            forecast_source=f"TEST_SOURCE_{n}",
            training_cutoff="2026-10-16T15:00:00Z",
            exit_rule="HOLD_TO_EXPIRY",
            scenarios=(
                TerminalScenario(D("100"), D(".2")),
                TerminalScenario(D("110"), D(".8")),
            ),
            prospective_independent_dates=20,
            matched_placebo_ci_lower_usd=D("2"),
        )
    return (
        ModelInput("a", "INDEPENDENT_STOCK_HISTORY", thesis("A")),
        ModelInput("b", "INDEPENDENT_BROAD_FEATURES", thesis("B")),
    )


def test_one_market_makes_one_across_strategies_decision():
    desk = evaluate_market(chain(), policy(), models())
    assert desk.families_evaluated == 7
    assert len(desk.decision.opportunities) == 7
    assert {d.strategy_id for d in desk.decision.opportunities} == {
        "S03", "S04", "S06", "S07", "S08", "S09", "S10",
    }
    assert desk.decision.broker_order_authority is False
    assert all(d.broker_order_authority is False for d in desk.decision.opportunities)
    # No separate priors for spreads vs iron structures; every eligible
    # payoff is challenged against exactly the same two frozen forecasts.
    assert all(len(row.model_net_ev_usd) == 2 for row in
               desk.decision.opportunities)
    assert any(row.rank is not None for row in desk.decision.opportunities)
    assert all(row.rank is None for row in desk.decision.opportunities
               if row.state == NO_TRADE)


def test_invalid_independent_spot_prevents_all_candidates():
    c = replace(chain(), spot_source="THETA_GREEK_MODEL")
    desk = evaluate_market(c, policy(), models())
    assert desk.families_evaluated == 0
    assert desk.decision.state == NO_TRADE
    assert desk.source_blockers == (
        "INDEPENDENT_CONTEMPORANEOUS_STOCK_REFERENCE_MISSING",
    )


def test_missing_forecast_emits_no_trade_with_reasons_for_all_seven():
    desk = evaluate_market(chain(), policy(), ())
    assert desk.decision.state == NO_TRADE
    assert desk.decision.provisional_count == 0
    assert len(desk.decision.opportunities) == 7
    assert all("NO_INDEPENDENT_FORECAST_MODELS" in row.missing_evidence
               for row in desk.decision.opportunities)
