"""One cross-strategy, cross-model opportunity ranking decision.

A market forecast is scored through the payoff of *every* eligible option
structure, not by counting strategy names or smile models as votes. Models
in one shared information lineage count as ONE evidence family, not three
independent confirmations. The benchmark is always doing nothing (net $0).

This is a deterministic research/manual-review ranker. It never places orders
or declares an executable, broker-verified profit opportunity.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Sequence

from src.decision.thesis_first_selection_v1 import (
    FrozenThesis, SelectionDecision, evaluate_candidate,
)
from src.research.strategy_falsification_v1 import (
    QuoteCostPolicy, Structure, dec,
)

VERSION = "UNIFIED_TRADE_RANKER_V1"
MAX_CANDIDATES = 200
MAX_MODELS_PER_CANDIDATE = 8
MIN_INDEPENDENT_MODEL_GROUPS = 2
NO_TRADE = "NO_TRADE"
MANUAL_REQUOTE = "CANDIDATE_FOR_MANUAL_REQUOTE_NOT_EXECUTABLE"


@dataclass(frozen=True)
class ModelInput:
    model_id: str
    # Known shared inputs/training data belong to the same dependence group.
    dependence_group: str
    thesis: FrozenThesis


@dataclass(frozen=True)
class OptionCandidate:
    snapshot_id: int
    underlying: str
    expiration: str
    structure: Structure
    cost_policy: QuoteCostPolicy
    model_inputs: tuple[ModelInput, ...]
    lane: str = "MAIN"


@dataclass(frozen=True)
class RankedOpportunity:
    snapshot_id: int
    underlying: str
    expiration: str
    strategy_id: str
    source_reference: str | None
    lane: str
    state: str
    rank: int | None
    conservative_net_ev_usd: Decimal | None
    risk_adjusted_score: Decimal | None
    assumed_worst_loss_usd: Decimal | None
    confirming_model_groups: int
    opposing_model_groups: int
    missing_evidence: tuple[str, ...]
    model_net_ev_usd: tuple[tuple[str, Decimal | None], ...]
    broker_order_authority: bool = False


@dataclass(frozen=True)
class MarketDecision:
    state: str
    top: RankedOpportunity | None
    opportunities: tuple[RankedOpportunity, ...]
    rejected_count: int
    provisional_count: int
    version: str = VERSION
    broker_order_authority: bool = False


def _risk_usd(assessed: Sequence[SelectionDecision]) -> Decimal | None:
    if not assessed:
        return None
    f = assessed[0].feasibility
    if f.gross_max_loss_usd is None or f.round_trip_cost_usd is None:
        return None
    try:
        risk = dec(f.gross_max_loss_usd) + dec(f.round_trip_cost_usd)
        if risk <= 0:
            return None
        return risk
    except (ValueError, TypeError, InvalidOperation):
        return None


def _assess_one(candidate: OptionCandidate) -> RankedOpportunity:
    blockers: set[str] = set()
    groups: dict[str, list[tuple[str, SelectionDecision]]] = {}
    if not candidate.underlying or not candidate.expiration:
        blockers.add("CANDIDATE_IDENTITY_MISSING")
    if not candidate.structure.reference:
        blockers.add("FROZEN_SOURCE_REFERENCE_MISSING")
    if not candidate.model_inputs:
        blockers.add("NO_INDEPENDENT_FORECAST_MODELS")
    if len(candidate.model_inputs) > MAX_MODELS_PER_CANDIDATE:
        blockers.add("MODEL_INPUT_COUNT_EXCEEDS_BOUND")

    seen_models: set[str] = set()
    results: list[tuple[str, Decimal | None]] = []
    for model in candidate.model_inputs[:MAX_MODELS_PER_CANDIDATE]:
        if not model.model_id or model.model_id in seen_models:
            blockers.add("MISSING_OR_DUPLICATE_MODEL_ID")
        seen_models.add(model.model_id)
        if not model.dependence_group:
            blockers.add("MODEL_INFORMATION_LINEAGE_UNDISCLOSED")
        outcome = evaluate_candidate(
            candidate.structure, candidate.cost_policy, model.thesis,
            underlying=candidate.underlying, expiration=candidate.expiration,
        )
        groups.setdefault(model.dependence_group, []).append((model.model_id, outcome))
        blockers.update(outcome.blockers)
        results.append((model.model_id, outcome.hypothetical_net_ev_usd))

    supporting = opposing = 0
    group_evs: list[Decimal] = []
    for _, observations in sorted(groups.items()):
        evs = [value.hypothetical_net_ev_usd for _, value in observations]
        # Multiple fits to the same surface give one conservatively aggregated
        # opinion, NEVER multiple votes in the ranking.
        if any(x is None for x in evs):
            blockers.add("MODEL_EXPECTANCY_NOT_RECONSTRUCTIBLE")
            continue
        worst = min(evs)
        group_evs.append(worst)
        if worst > 0:
            supporting += 1
        else:
            opposing += 1
    if len(groups) < MIN_INDEPENDENT_MODEL_GROUPS:
        blockers.add("TOO_FEW_DISTINCT_INFORMATION_GROUPS")
    if opposing:
        blockers.add("INDEPENDENT_MODEL_DISAGREES_ON_POSITIVE_EV")
    if not group_evs:
        blockers.add("NO_MODELED_NET_RETURN")
    risk = _risk_usd([
        outcome for observations in groups.values() for _, outcome in observations
    ])
    if risk is None:
        blockers.add("ALL_IN_MAX_LOSS_NOT_EVIDENCED")
    robust_ev = min(group_evs) if group_evs else None
    if robust_ev is None or robust_ev <= 0:
        blockers.add("CANNOT_BEAT_NO_TRADE_BASELINE")
    score = robust_ev / risk if (
        robust_ev is not None and robust_ev > 0
        and risk is not None and not blockers
    ) else None
    state = MANUAL_REQUOTE if not blockers else NO_TRADE
    return RankedOpportunity(
        snapshot_id=candidate.snapshot_id,
        underlying=candidate.underlying,
        expiration=candidate.expiration,
        strategy_id=candidate.structure.strategy_id,
        source_reference=candidate.structure.reference,
        lane=candidate.lane,
        state=state, rank=None,
        conservative_net_ev_usd=robust_ev,
        risk_adjusted_score=score,
        assumed_worst_loss_usd=risk,
        confirming_model_groups=supporting,
        opposing_model_groups=opposing,
        missing_evidence=tuple(sorted(blockers)),
        model_net_ev_usd=tuple(results),
    )


def rank_market_opportunities(
    candidates: Sequence[OptionCandidate],
) -> MarketDecision:
    """One comparison table for ALL strategy families; nothing is promoted.

    Best *hypothetical* robust net expectancy after assumed entry/exit costs
    and loss-capital normalization, conditional on fully disclosed evidence.
    All candidate inputs must have been frozen before their evaluation outcome.
    """
    if len(candidates) > MAX_CANDIDATES:
        raise ValueError("CANDIDATE_COUNT_EXCEEDS_BOUNDED_RANKING")
    # Same contract, strategy and data-cut is one economic proposal; never
    # present repeated captures as multiple independent trade opportunities.
    seen: set[tuple[int, str, str, str, str | None]] = set()
    scored: list[RankedOpportunity] = []
    for candidate in candidates:
        key = (
            candidate.snapshot_id, candidate.underlying, candidate.expiration,
            candidate.structure.strategy_id, candidate.structure.reference,
        )
        if key in seen:
            raise ValueError("DUPLICATED_FROZEN_OPTION_CANDIDATE")
        seen.add(key)
        scored.append(_assess_one(candidate))
    eligible = sorted(
        (s for s in scored if s.state == MANUAL_REQUOTE),
        key=lambda x: (
            -x.risk_adjusted_score, -x.conservative_net_ev_usd,
            x.underlying, x.expiration, x.strategy_id,
        ),
    )
    ranked = [RankedOpportunity(**{
        **s.__dict__, "rank": index,
    }) for index, s in enumerate(eligible, 1)]
    blocked = sorted(
        (s for s in scored if s.state != MANUAL_REQUOTE),
        key=lambda x: (x.underlying, x.expiration, x.strategy_id),
    )
    top = ranked[0] if ranked else None
    return MarketDecision(
        state=MANUAL_REQUOTE if top else NO_TRADE,
        top=top,
        opportunities=tuple([*ranked, *blocked]),
        rejected_count=len(blocked),
        provisional_count=len(ranked),
    )
