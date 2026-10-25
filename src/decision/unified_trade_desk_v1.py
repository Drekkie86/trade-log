"""One call: frozen market chain + forecasting models -> ranked options desk.

All strategy families use identical forecasts, costs, risk and evidence gates.
This intentionally replaces the conceptual butterfly->optional-comparisons
dependency. Pure research, no daemon/Streamlit/DB write/order integration yet.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from src.decision.unified_trade_ranker_v1 import (
    MarketDecision, ModelInput, OptionCandidate, rank_market_opportunities,
)
from src.research.independent_family_discovery_v1 import (
    FrozenChain, IndependentDiscovery, discover_independent_families,
)
from src.research.strategy_falsification_v1 import QuoteCostPolicy


@dataclass(frozen=True)
class UnifiedTradeDesk:
    source_state: str
    source_blockers: tuple[str, ...]
    families_evaluated: int
    decision: MarketDecision
    authority: str = "NONE"


def evaluate_market(
    chain: FrozenChain,
    policy: QuoteCostPolicy,
    models: Sequence[ModelInput],
    *,
    lane: str = "MAIN",
) -> UnifiedTradeDesk:
    """Produces one ranked decision, not independent strategy-page verdicts.

    A shared price-distribution forecast can assess a spread, straddle and
    iron condor without new strategy-specific forecasts. A convergence
    early exit cannot borrow a terminal-only expiry payoff estimator.
    """
    discovery: IndependentDiscovery = discover_independent_families(chain, policy)
    candidates = tuple(
        OptionCandidate(
            snapshot_id=chain.snapshot_id,
            underlying=chain.underlying,
            expiration=structure.legs[0].expiration or "",
            structure=structure,
            cost_policy=policy,
            model_inputs=tuple(models),
            lane=lane,
        )
        for structure in discovery.source_structures
    )
    result = rank_market_opportunities(candidates)
    return UnifiedTradeDesk(
        source_state=discovery.state,
        source_blockers=discovery.blockers,
        families_evaluated=len(candidates),
        decision=result,
    )
