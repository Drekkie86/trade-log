"""Multi-family construction is independent of butterfly-scanner output."""
from dataclasses import replace
from decimal import Decimal as D

from src.decision.thesis_first_selection_v1 import (
    EXPIRY_EXIT, FrozenThesis, TerminalScenario, NO_TRADE,
)
from src.research.independent_family_discovery_v1 import (
    FAMILIES, FrozenChain, FrozenQuote, discover_independent_families,
)
from src.research.massive_underlying_observation_v1 import STOCK_PRICE_SOURCE
from src.research.strategy_falsification_v1 import QuoteCostPolicy

CUT = "2026-10-19T15:00:00Z"
QTIME = "2026-10-19T14:59:55Z"


def policy():
    return QuoteCostPolicy(
        option_cost_per_contract_side_usd=D("1"),
        stock_round_trip_cost_usd=None,
        eur_to_usd=D("1.15"),
        cost_provenance="TEST_PUBLIC_TARIFF_ASSUMPTION",
        fx_provenance="TEST_ECB_SOURCE",
        max_quote_age_seconds=15, max_leg_quote_skew_seconds=15,
        bankroll_eur=D("500"),
        additional_round_trip_cost_usd=D("2"), tax_cost_usd=D("1"),
        fx_observed_at=QTIME,
    )


def source_chain():
    quotes = []
    for right in ("C", "P"):
        for strike in (90, 95, 100, 105, 110):
            idx = len(quotes) + 1
            quotes.append(FrozenQuote(
                source_id=idx, snapshot_id=88,
                expiration="2026-10-23", right=right, strike=D(str(strike)),
                bid=D("1.00"), ask=D("1.10"), quote_at=QTIME,
                reference_multiplier=D("100"), bid_size=D("5"), ask_size=D("5"),
            ))
    return FrozenChain(
        snapshot_id=88, underlying="XYZ", captured_at=CUT,
        spot=D("100"), spot_source=STOCK_PRICE_SOURCE, spot_at=QTIME,
        quotes=tuple(quotes),
    )


def test_seven_families_independently_discovered_from_chain_not_butterflies():
    output = discover_independent_families(source_chain(), policy())
    assert output.state == "RESEARCH_ONLY_NO_TRADE"
    assert output.strategy_ids == FAMILIES
    assert len(output.decisions) == 7
    assert len(output.source_quote_sets) == 7
    assert output.distinct_expiries == 1
    assert all(d.state == NO_TRADE for d in output.decisions)
    assert all("NO_PRECOMMITTED_PREDICTIVE_THESIS" in d.blockers
               for d in output.decisions)
    assert all(d.authority == "NONE" and not d.eligible_for_live_trading
               for d in output.decisions)
    assert all(set(ids) <= set(range(1, 11)) for ids in output.source_quote_sets)
    assert all(d.feasibility.state != "FAILED_STRUCTURE" for d in output.decisions)


def test_stale_or_model_derived_stock_price_cannot_seed_discovery():
    chain = source_chain()
    for test in (
        replace(chain, spot_source="THETADATA_GREEK_MODEL"),
        replace(chain, spot=None),
        replace(chain, spot_at="2026-10-19T14:59:20Z"),
        replace(chain, spot_at="2026-10-19T15:00:01Z"),
        replace(chain, spot_source=None),
    ):
        result = discover_independent_families(test, policy())
        assert result.state == "NO_DATA"
        assert result.decisions == ()
        assert "INDEPENDENT_CONTEMPORANEOUS_STOCK_REFERENCE_MISSING" in result.blockers


def test_mixed_snapshot_and_duplicate_contract_fail_closed():
    chain = source_chain()
    altered = replace(chain.quotes[0], snapshot_id=89)
    output = discover_independent_families(
        replace(chain, quotes=(altered, *chain.quotes[1:])), policy()
    )
    assert output.state == "SOURCE_EVIDENCE_REJECTED"
    duplicate = replace(chain.quotes[1], strike=chain.quotes[0].strike)
    result = discover_independent_families(
        replace(chain, quotes=(chain.quotes[0], duplicate, *chain.quotes[2:])),
        policy(),
    )
    assert result.state == "SOURCE_EVIDENCE_REJECTED"
    assert result.decisions == ()


def test_missing_reference_multiplier_is_not_assumed_to_be_100():
    chain = source_chain()
    altered = replace(chain.quotes[2], reference_multiplier=None)
    out = discover_independent_families(
        replace(chain, quotes=(*chain.quotes[:2], altered, *chain.quotes[3:])),
        policy(),
    )
    assert out.state == "SOURCE_EVIDENCE_REJECTED"
    assert "LISTING_REFERENCE_MULTIPLIER_MISSING" in out.blockers


def test_forecast_for_one_family_not_transferred_to_unrelated_strategies():
    chain = source_chain()
    thesis = FrozenThesis(
        thesis_id="XYZ_UP_001", family="DIRECTIONAL_UP",
        frozen_at=QTIME, underlying="XYZ", expiration="2026-10-23",
        forecast_model_version="MODEL_V1", forecast_source="INDEPENDENT",
        training_cutoff="2026-10-16T15:00:00Z", exit_rule=EXPIRY_EXIT,
        scenarios=(TerminalScenario(D("110"), D("1")),),
        prospective_independent_dates=20,
        matched_placebo_ci_lower_usd=D("3"),
    )
    result = discover_independent_families(
        chain, policy(), theses_by_family={"S03": thesis}
    )
    assert result.decisions[0].thesis_id == "XYZ_UP_001"
    assert all(d.thesis_id is None for d in result.decisions[1:])
    assert all("NO_PRECOMMITTED_PREDICTIVE_THESIS" in d.blockers
               for d in result.decisions[1:])


def test_directional_thesis_cannot_approve_a_short_volatility_package():
    chain = source_chain()
    directional = FrozenThesis(
        thesis_id="DIRECTION_ONLY", family="DIRECTIONAL_UP", frozen_at=QTIME,
        underlying="XYZ", expiration="2026-10-23",
        forecast_model_version="MODEL_V1", forecast_source="TEST_PRECOMMIT",
        training_cutoff="2026-10-16T15:00:00Z", exit_rule=EXPIRY_EXIT,
        scenarios=(TerminalScenario(D("100"), D("1")),),
        prospective_independent_dates=25,
        matched_placebo_ci_lower_usd=D("3"),
    )
    result = discover_independent_families(
        chain, policy(), theses_by_family={"S09": directional}
    )
    condor = next(d for d in result.decisions if d.strategy_id == "S09")
    assert condor.feasibility.state != "FAILED_STRUCTURE"
    assert "THESIS_DOES_NOT_SUPPORT_STRUCTURE_FAMILY" in condor.blockers
    assert condor.state == NO_TRADE


def test_quote_from_future_prevents_all_research_selection():
    chain = source_chain()
    future = replace(chain.quotes[2], quote_at="2026-10-19T15:00:03Z")
    out = discover_independent_families(
        replace(chain, quotes=(*chain.quotes[:2], future, *chain.quotes[3:])),
        policy(),
    )
    assert out.state == "SOURCE_EVIDENCE_REJECTED"
    assert "QUOTE_FROM_FUTURE" in out.blockers
