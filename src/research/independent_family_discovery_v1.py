"""Independent, butterfly-free discovery of seven option-only expressions.

Pure research from a single frozen chain. This *does not* infer a predictive
thesis from payoff geometry or select strikes after seeing an outcome. A
missing independent spot or stale cross-provider reference fails closed.
No DB writes, broker calls, shadow admissions or live recommendations.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Mapping

from src.decision.thesis_first_selection_v1 import (
    FrozenThesis, SelectionDecision, evaluate_candidate,
)
from src.research.massive_underlying_observation_v1 import (
    MAX_AGE_SECONDS, STOCK_PRICE_SOURCES,
)
from src.research.strategy_falsification_v1 import (
    Leg, QuoteCostPolicy, Structure, dec, utc,
)

VERSION = "INDEPENDENT_OPTION_FAMILY_DISCOVERY_V1"
FAMILIES = ("S03", "S04", "S06", "S07", "S08", "S09", "S10")
MAX_QUOTES = 2500
MAX_EXPIRIES = 6


@dataclass(frozen=True)
class FrozenQuote:
    source_id: int
    snapshot_id: int
    expiration: str
    right: str
    strike: Decimal
    bid: Decimal | None
    ask: Decimal | None
    quote_at: str | None
    reference_multiplier: Decimal | None
    quoted_multiplier: Decimal | None = None
    bid_size: Decimal | None = None
    ask_size: Decimal | None = None


@dataclass(frozen=True)
class FrozenChain:
    snapshot_id: int
    underlying: str
    captured_at: str
    spot: Decimal | None
    spot_source: str | None
    spot_at: str | None
    quotes: tuple[FrozenQuote, ...]
    source_blocker: str | None = None


@dataclass(frozen=True)
class IndependentDiscovery:
    state: str
    blockers: tuple[str, ...]
    snapshot_id: int
    decisions: tuple[SelectionDecision, ...]
    source_quote_sets: tuple[tuple[int, ...], ...]
    distinct_expiries: int
    authority: str = "NONE"
    source_structures: tuple[Structure, ...] = ()

    @property
    def strategy_ids(self) -> tuple[str, ...]:
        return tuple(d.strategy_id for d in self.decisions)


def _leg(q: FrozenQuote, side: str, quantity: int = 1) -> Leg:
    mult = q.reference_multiplier
    if mult is None:
        raise ValueError("LISTING_REFERENCE_MULTIPLIER_MISSING")
    if q.quoted_multiplier is not None and q.quoted_multiplier != mult:
        raise ValueError("QUOTE_REFERENCE_MULTIPLIER_MISMATCH")
    if mult <= 0:
        raise ValueError("INVALID_MULTIPLIER")
    return Leg(
        kind="CALL" if q.right == "C" else "PUT",
        side=side, quantity=quantity, multiplier=mult,
        strike=q.strike, expiration=q.expiration,
        bid=q.bid, ask=q.ask, quote_at=q.quote_at,
        bid_size=q.bid_size, ask_size=q.ask_size,
        source_id=str(q.source_id),
    )


def _stock_reference_valid(chain: FrozenChain) -> bool:
    if chain.spot is None or chain.spot_source not in STOCK_PRICE_SOURCES or not chain.spot_at:
        return False
    try:
        if dec(chain.spot) <= 0:
            return False
        age = (utc(chain.captured_at) - utc(chain.spot_at)).total_seconds()
        return 0 <= age <= MAX_AGE_SECONDS
    except (ValueError, TypeError):
        return False


def _templates(
    qmap: dict[tuple[str, Decimal], FrozenQuote],
    spot: Decimal,
) -> dict[str, tuple[Leg, ...]]:
    """Freeze deterministic adjacent-ATM geometry BEFORE any expiry evidence."""
    common = sorted(
        {strike for right, strike in qmap if right == "C"}
        & {strike for right, strike in qmap if right == "P"}
    )
    if len(common) < 3:
        return {}
    center = min(common, key=lambda k: (abs(k - spot), k))
    below = sorted((k for k in common if k < center), reverse=True)
    above = sorted((k for k in common if k > center))
    if not below or not above:
        return {}
    lo, hi = below[0], above[0]
    call = lambda strike, side, quantity=1: _leg(qmap["C", strike], side, quantity)
    put = lambda strike, side, quantity=1: _leg(qmap["P", strike], side, quantity)
    models = {
        "S03": (call(center, "BUY"), call(hi, "SELL")),
        "S04": (put(center, "BUY"), put(lo, "SELL")),
        "S06": (put(center, "BUY"), call(center, "BUY")),
        "S07": (put(lo, "BUY"), call(hi, "BUY")),
        "S10": (put(lo, "BUY"), put(center, "SELL"),
                call(center, "SELL"), call(hi, "BUY")),
    }
    if center - lo == hi - center:
        models["S08"] = (
            call(lo, "BUY"), call(center, "SELL", 2), call(hi, "BUY")
        )
    if len(below) >= 2 and len(above) >= 2:
        models["S09"] = (
            put(below[1], "BUY"), put(lo, "SELL"),
            call(hi, "SELL"), call(above[1], "BUY"),
        )
    return models


def discover_independent_families(
    chain: FrozenChain,
    policy: QuoteCostPolicy,
    *,
    market_thesis: FrozenThesis | None = None,
    theses_by_family: Mapping[str, FrozenThesis] | None = None,
) -> IndependentDiscovery:
    """Seven-option-family search directly from a snapshot, not butterfly proposals.

    All candidate strategies share the identical cost and thesis evidence
    gates. A family cannot borrow a signal belonging to another family.
    """
    missing: list[str] = []
    if chain.source_blocker:
        missing.append(chain.source_blocker)
    if not _stock_reference_valid(chain):
        missing.append("INDEPENDENT_CONTEMPORANEOUS_STOCK_REFERENCE_MISSING")
    if not chain.underlying.strip():
        missing.append("UNDERLYING_MISSING")
    if len(chain.quotes) > MAX_QUOTES or (
        not chain.quotes and _stock_reference_valid(chain)
    ):
        missing.append("SOURCE_OPTION_CHAIN_MISSING_OR_EXCEEDS_BOUND")
    if missing:
        return IndependentDiscovery(
            "NO_DATA", tuple(sorted(missing)), chain.snapshot_id, (), (), 0,
        )

    q_by_expiry: dict[str, dict[tuple[str, Decimal], FrozenQuote]] = {}
    quote_ids: set[int] = set()
    try:
        decision_at = utc(chain.captured_at)
        for q in chain.quotes:
            if q.snapshot_id != chain.snapshot_id or q.source_id in quote_ids:
                raise ValueError("QUOTE_SNAPSHOT_OR_IDENTITY_CONFLICT")
            quote_ids.add(q.source_id)
            if q.right not in ("C", "P") or dec(q.strike) <= 0:
                raise ValueError("INVALID_OPTION_RIGHT_OR_STRIKE")
            if not q.expiration or q.expiration < decision_at.date().isoformat():
                continue
            if q.quote_at is None:
                raise ValueError("QUOTE_TIME_NOT_AVAILABLE")
            if utc(q.quote_at) > decision_at:
                raise ValueError("QUOTE_FROM_FUTURE")
            key = (q.right, dec(q.strike))
            bucket = q_by_expiry.setdefault(q.expiration, {})
            if key in bucket:
                raise ValueError("DUPLICATE_CONTRACT_IN_SNAPSHOT")
            bucket[key] = q
        if len(q_by_expiry) > MAX_EXPIRIES:
            raise ValueError("EXPIRY_COUNT_EXCEEDS_BOUNDED_DISCOVERY")
        decisions: list[SelectionDecision] = []
        source_structures: list[Structure] = []
        provenance: list[tuple[int, ...]] = []
        theses = theses_by_family or {}
        if market_thesis is not None and theses:
            raise ValueError("MARKET_AND_FAMILY_FORECASTS_AMBIGUOUS")
        for expiration in sorted(q_by_expiry):
            qmap = q_by_expiry[expiration]
            # A single invalid leg blocks this expiry's candidate expressions,
            # without creating invented replacements or guessed multipliers.
            templates = _templates(qmap, dec(chain.spot))
            for strategy_id in FAMILIES:
                legs = templates.get(strategy_id)
                if legs is None:
                    continue
                source_ids = tuple(int(l.source_id) for l in legs)
                structure = Structure(
                    strategy_id=strategy_id,
                    signal_version=VERSION + ":RESEARCH_ONLY",
                    decision_at=chain.captured_at,
                    legs=legs,
                    reference=(
                        f"snapshot:{chain.snapshot_id}:"
                        f"{chain.underlying}:{expiration}:{strategy_id}"
                    ),
                )
                decision = evaluate_candidate(
                    structure, policy,
                    market_thesis if market_thesis is not None else theses.get(strategy_id),
                    underlying=chain.underlying, expiration=expiration,
                )
                decisions.append(decision)
                source_structures.append(structure)
                provenance.append(source_ids)
    except (ValueError, TypeError, KeyError) as exc:
        return IndependentDiscovery(
            "SOURCE_EVIDENCE_REJECTED", (str(exc),),
            chain.snapshot_id, (), (), 0,
        )

    return IndependentDiscovery(
        "RESEARCH_ONLY_NO_TRADE" if decisions else "NO_SUPPORTED_STRATEGY_GEOMETRY",
        () if decisions else ("NO_MATCHING_SAME_SNAPSHOT_OPTION_GEOMETRY",),
        chain.snapshot_id, tuple(decisions), tuple(provenance),
        len(q_by_expiry), source_structures=tuple(source_structures),
    )
