"""Read-only Stage-0 competition using SAME frozen market evidence as Trade Ideas.

NOT a signal generator, prediction, or additional recommendation system.
A local IV anomaly does not imply a directional vertical edge. The only
purpose here is to compare real sourced package geometry and reveal missing
evidence before an independent hypothesis is approved and precommitted.

A single snapshot ID and decision cut-off are enforced across every leg.
No DB writes, provider requests, pseudo-spots, invented sizes, broker fills,
outcome-conditioned candidate choices or manual invented premiums.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo
from typing import Sequence

from src.database.repository import get_connection
from src.decision.trade_ideas import TradeIdea
from src.research.shadow_intrinsic_admission_v1 import USD_COST_PER_CONTRACT_SIDE_MINOR
from src.research.live_pipeline import parse_thetadata_market_timestamp
from src.research.strategy_falsification_v1 import (
    CATALOGUE, LEGACY_REVERSE_ID, Feasibility, Leg, QuoteCostPolicy,
    Structure, dec, evaluate, utc,
)

VERSION = "ASOF_REAL_QUOTE_STRATEGY_COMPARISON_V1"
# Reuse Stage-0's existing strict timestamp limits; these are not assumptions
# about the broker's executable package prices.
QUOTE_MAX_AGE_SECONDS = 15
MAX_LEG_SKEW_SECONDS = 15
MAX_PROPOSALS = 40
MAX_QUOTES_PER_SNAPSHOT = 2500
RESEARCH_ONLY = "RESEARCH_ONLY_NO_INDEPENDENT_DIRECTIONAL_SIGNAL"
OPTION_ONLY_FAMILIES = ("S03", "S04", "S06", "S07", "S08", "S09", "S10")


@dataclass(frozen=True)
class Comparison:
    proposal_id: int
    underlying: str
    expiration: str
    snapshot_id: int | None
    decision_at: str | None
    strategy_id: str
    family_name: str
    source_quote_ids: tuple[int, ...]
    signal_evidence: str
    comparison_state: str
    reasons: tuple[str, ...]
    feasibility: Feasibility | None = None

    def display_row(self) -> dict[str, object]:
        f = self.feasibility
        return {
            "Stock": self.underlying,
            "Expiry": self.expiration,
            "Strategy": self.family_name,
            "Decision snapshot": self.snapshot_id,
            "Source quote IDs": ", ".join(map(str, self.source_quote_ids)) or "—",
            "Payoff feasibility": f.state if f else self.comparison_state,
            "Gross max loss ($)": f.gross_max_loss_usd if f else None,
            "Gross max profit ($)": f.gross_max_profit_usd if f else None,
            "Estimated all-in capital (€)": f.conservative_capital_eur if f else None,
            "Status": self.comparison_state,
            "Missing evidence": ", ".join(self.reasons) or "—",
        }


def _quote_time_asof(raw: str | None) -> str | None:
    """Use the pre-existing documented ThetaData America/New_York convention.

    Preserve the raw database timestamp. For a naive local DST fold or gap,
    refuse an arbitrary interpretation; a quote cannot have two valid UTC
    instants in an as-of research comparison.
    """
    if not raw:
        return None
    parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        ny = ZoneInfo("America/New_York")
        early = parsed.replace(tzinfo=ny, fold=0)
        late = parsed.replace(tzinfo=ny, fold=1)
        if early.utcoffset() != late.utcoffset():
            raise ValueError("AMBIGUOUS_PROVIDER_DST_TIMESTAMP")
        if early.astimezone(timezone.utc).astimezone(ny).replace(tzinfo=None) != parsed:
            raise ValueError("NONEXISTENT_PROVIDER_DST_TIMESTAMP")
    return parse_thetadata_market_timestamp(str(raw)).astimezone(timezone.utc).isoformat()


def _quote_leg(row: sqlite3.Row, *, side: str, quantity: int = 1) -> Leg:
    # Quote rows historically have NULL multipliers. Resolve via the exact
    # persisted MASSIVE listing contract in the *same research run* instead of
    # inventing a default 100. Conflicts fail closed.
    quote_multiplier = row["quote_multiplier"]
    reference_multiplier = row["reference_multiplier"]
    if (quote_multiplier is not None and reference_multiplier is not None
            and dec(quote_multiplier) != dec(reference_multiplier)):
        raise ValueError("QUOTE_AND_LISTING_MULTIPLIER_DISAGREE")
    multiplier = quote_multiplier if quote_multiplier is not None else reference_multiplier
    if multiplier is None:
        raise ValueError("CONTRACT_MULTIPLIER_NOT_EVIDENCED")
    # Missing option-side depth is unknown; do not substitute open interest
    # or daily volume. No synthetic quotes are allowed in this adapter.
    return Leg(
        kind="CALL" if row["right"] == "C" else "PUT",
        side=side,
        quantity=quantity,
        multiplier=dec(multiplier),
        strike=dec(row["strike"]),
        expiration=str(row["expiration"]),
        bid=None if row["bid"] is None else dec(row["bid"]),
        ask=None if row["ask"] is None else dec(row["ask"]),
        quote_at=_quote_time_asof(row["quote_at"]),
        source_id=str(row["id"]),
    )


def _policy(*, allocated_eur: Decimal, rate: float | None,
            fx_at: str | None, fx_source: str | None) -> QuoteCostPolicy:
    # Broker tax/slippage/exit execution are genuinely unverified, so they
    # MUST remain None. 'Affordable' and a recommendation are impossible.
    return QuoteCostPolicy(
        option_cost_per_contract_side_usd=Decimal(USD_COST_PER_CONTRACT_SIDE_MINOR) / 100,
        stock_round_trip_cost_usd=None,
        eur_to_usd=None if rate is None else dec(rate),
        cost_provenance="SAXO_BE_SHADOW_COST_CEILING_V1_ASSUMED_NOT_BROKER",
        fx_provenance=fx_source,
        max_quote_age_seconds=QUOTE_MAX_AGE_SECONDS,
        max_leg_quote_skew_seconds=MAX_LEG_SKEW_SECONDS,
        additional_round_trip_cost_usd=None,
        tax_cost_usd=None,
        fx_observed_at=fx_at,
        bankroll_eur=allocated_eur,
    )


def _unique(qmap: dict[tuple[str, str], list[sqlite3.Row]],
            right: str, strike: float) -> sqlite3.Row:
    rows = qmap.get((right, str(dec(strike).normalize())), [])
    if len(rows) != 1:
        raise ValueError(
            "MISSING_SAME_SNAPSHOT_QUOTE" if not rows
            else "AMBIGUOUS_SAME_SNAPSHOT_CONTRACT"
        )
    return rows[0]


def _load_source(conn: sqlite3.Connection, snapshot_id: int):
    snap = conn.execute(
        "SELECT id,underlying,captured_at FROM market_snapshots WHERE id=?",
        (snapshot_id,),
    ).fetchone()
    if snap is None:
        raise ValueError("MISSING_FROZEN_SNAPSHOT")
    # Include all expiration legs only after identity and as-of checks;
    # same snapshot prevents mixing pricing from different collection cuts.
    return snap


def _fx_asof(conn: sqlite3.Connection, cut: str):
    row = conn.execute(
        """SELECT rate, observed_at, provider, provenance
           FROM fx_observations
           WHERE base_currency='EUR' AND quote_currency='USD'
             AND observed_at <= ?
           ORDER BY observed_at DESC,id DESC LIMIT 1""",
        (cut,),
    ).fetchone()
    if row is None:
        return None, None, None
    try:
        if utc(str(row["observed_at"])) > utc(cut) or dec(row["rate"]) <= 0:
            return None, None, None
    except (ValueError, TypeError):
        return None, None, None
    return float(row["rate"]), str(row["observed_at"]), (
        str(row["provider"]) + ":" + str(row["provenance"])
    )


def _missing(idea: TradeIdea, sid: str, code: str,
             snapshot_id: int | None = None) -> Comparison:
    return Comparison(
        idea.proposal_id, idea.underlying, idea.expiration, snapshot_id,
        idea.as_of, sid, CATALOGUE.get(sid, (sid, ""))[0],
        (), "NO_APPROVED_DISTINCT_PREDICTIVE_SIGNAL",
        "NOT_EVALUATED", (code,),
    )


def _evaluate_one(
    idea: TradeIdea, sid: str, snap: sqlite3.Row,
    qmap: dict[tuple[str, str], list[sqlite3.Row]],
    by_id: dict[int, sqlite3.Row],
    policy: QuoteCostPolicy,
) -> Comparison:
    strikes = sorted(set(idea.strikes))
    if len(strikes) != 3 or not strikes[0] < strikes[1] < strikes[2]:
        return _missing(idea, sid, "BUTTERFLY_CENTRE_AND_WINGS_REQUIRED", int(snap["id"]))
    lo, centre, hi = strikes
    try:
        if sid == "S03":
            legs = (_quote_leg(_unique(qmap, "C", lo), side="BUY"),
                    _quote_leg(_unique(qmap, "C", centre), side="SELL"))
        elif sid == "S04":
            legs = (_quote_leg(_unique(qmap, "P", hi), side="BUY"),
                    _quote_leg(_unique(qmap, "P", centre), side="SELL"))
        elif sid == "S06":
            legs = (_quote_leg(_unique(qmap, "P", centre), side="BUY"),
                    _quote_leg(_unique(qmap, "C", centre), side="BUY"))
        elif sid == "S07":
            legs = (_quote_leg(_unique(qmap, "P", lo), side="BUY"),
                    _quote_leg(_unique(qmap, "C", hi), side="BUY"))
        elif sid == "S09":
            call_strikes_above = sorted(
                (dec(k) for (right, k) in qmap
                 if right == "C" and dec(k) > dec(hi))
            )
            if not call_strikes_above:
                raise ValueError("IRON_CONDOR_OUTER_CALL_NOT_IN_SNAPSHOT")
            legs = (_quote_leg(_unique(qmap, "P", lo), side="BUY"),
                    _quote_leg(_unique(qmap, "P", centre), side="SELL"),
                    _quote_leg(_unique(qmap, "C", hi), side="SELL"),
                    _quote_leg(_unique(qmap, "C", float(call_strikes_above[0])), side="BUY"))
        elif sid == "S10":
            legs = (_quote_leg(_unique(qmap, "P", lo), side="BUY"),
                    _quote_leg(_unique(qmap, "P", centre), side="SELL"),
                    _quote_leg(_unique(qmap, "C", centre), side="SELL"),
                    _quote_leg(_unique(qmap, "C", hi), side="BUY"))
        elif sid in ("S08", LEGACY_REVERSE_ID):
            legs = tuple(
                _quote_leg(by_id[int(l.option_quote_id)], side=l.side, quantity=l.quantity)
                for l in idea.legs
            )
            # Existing proposal was frozen earlier; do not reprice with some
            # newer quote ID or accept a structurally different strike/right.
            for source, proposal_leg in zip(legs, idea.legs):
                if (source.strike != dec(proposal_leg.strike)
                    or source.kind != ("CALL" if proposal_leg.right == "C" else "PUT")
                    or source.multiplier != dec(proposal_leg.multiplier)):
                    raise ValueError("ORIGINAL_PROPOSAL_QUOTE_IDENTITY_MISMATCH")
                expected_entry = source.ask if source.side == "BUY" else source.bid
                if expected_entry is None or expected_entry != dec(proposal_leg.entry_price):
                    raise ValueError("ORIGINAL_FROZEN_ENTRY_PRICE_MISMATCH")
        else:
            raise ValueError("NOT_AN_APPLICABLE_STAGE0_EXPRESSION")
        candidate = Structure(
            strategy_id=sid,
            signal_version=VERSION + ":UNVALIDATED_SIGNAL",
            decision_at=str(snap["captured_at"]),
            legs=legs,
            reference=f"research_snapshot:{snap['id']}:proposal:{idea.proposal_id}",
        )
        result = evaluate(candidate, policy)
        reasons = list(result.reasons)
        # Structural quotes exist for distinct payoff shapes, but none
        # inherits a directional or volatility prediction from the local-IV
        # residual. Even the original butterfly is unproven versus placebo.
        reasons.append("NO_PROSPECTIVE_STRATEGY_SPECIFIC_EDGE_EVIDENCE")
        if any(leg.side == "SELL" for leg in legs):
            reasons.append("AMERICAN_EARLY_ASSIGNMENT_PATH_UNVERIFIED")
        return Comparison(
            idea.proposal_id, idea.underlying, idea.expiration,
            int(snap["id"]), str(snap["captured_at"]),
            sid, CATALOGUE.get(sid, ("Legacy reverse fly", ""))[0],
            tuple(int(l.source_id) for l in legs),
            ("LOCAL_IV_RESIDUAL_UNVALIDATED" if sid in ("S08", LEGACY_REVERSE_ID)
             else "NO_APPROVED_DISTINCT_PREDICTIVE_SIGNAL"),
            RESEARCH_ONLY, tuple(sorted(set(reasons))), result,
        )
    except (KeyError, ValueError, TypeError) as exc:
        return _missing(idea, sid, str(exc), int(snap["id"]))


def compare_real_snapshot_strategies(
    ideas: Sequence[TradeIdea], *, allocated_eur: str,
    db_path=None,
) -> tuple[Comparison, ...]:
    """Compare actual original quote snapshots, bounded by latest ideas.

    No scans over synthetic Stage-0 presets. No persisted new candidates.
    All option-only instruments are research comparisons, never approvals.
    Only a strategy-specific predictive signal with independent validation can
    graduate into the main recommendation engine in a subsequent version.
    """
    allocation = dec(allocated_eur)
    if allocation <= 0 or allocation > 500:
        raise ValueError("RESEARCH_BUDGET_OUTSIDE_EXPLICIT_500_EUR_LIMIT")
    if len(ideas) > MAX_PROPOSALS:
        raise ValueError("PROPOSAL_COUNT_EXCEEDS_BOUNDED_COMPARISON")
    result: list[Comparison] = []
    conn = get_connection(db_path)
    try:
        conn.execute("PRAGMA query_only=ON")
        cache: dict[tuple[int, str], tuple] = {}
        for idea in ideas:
            if not idea.as_of or not idea.legs:
                result.extend(_missing(idea, sid, "NO_ORIGINAL_PROPOSAL_QUOTE")
                              for sid in OPTION_ONLY_FAMILIES)
                continue
            first_id = int(idea.legs[0].option_quote_id)
            source = conn.execute(
                "SELECT snapshot_id FROM option_quotes WHERE id=?", (first_id,)
            ).fetchone()
            if source is None:
                result.extend(_missing(idea, sid, "ORIGINAL_QUOTE_NOT_FOUND")
                              for sid in OPTION_ONLY_FAMILIES)
                continue
            snapshot_id = int(source["snapshot_id"])
            key = (snapshot_id, idea.expiration)
            if key not in cache:
                snap = _load_source(conn, snapshot_id)
                source_rows = conn.execute(
                    """SELECT oq.id,oq.snapshot_id,oq.right,oq.strike,oq.expiration,
                              oq.quote_at,oq.bid,oq.ask,
                              oq.shares_per_contract AS quote_multiplier,
                              lrc.shares_per_contract AS reference_multiplier
                       FROM option_quotes oq
                       JOIN market_snapshots ms ON ms.id=oq.snapshot_id
                       LEFT JOIN listing_reference_contracts lrc
                         ON lrc.research_run_id=ms.research_run_id
                        AND lrc.provider='MASSIVE'
                        AND lrc.underlying=ms.underlying
                        AND lrc.expiration=oq.expiration
                        AND lrc.strike=oq.strike AND lrc.right=oq.right
                       WHERE oq.snapshot_id=? AND oq.expiration=?
                       ORDER BY oq.id
                       LIMIT ?""",
                    (snapshot_id, idea.expiration, MAX_QUOTES_PER_SNAPSHOT + 1),
                ).fetchall()
                if len(source_rows) > MAX_QUOTES_PER_SNAPSHOT:
                    raise ValueError("SNAPSHOT_CHAIN_EXCEEDS_BOUNDED_READ")
                by_id = {int(q["id"]): q for q in source_rows}
                by_strike: dict[tuple[str, str], list[sqlite3.Row]] = {}
                for q in source_rows:
                    by_strike.setdefault(
                        (str(q["right"]), str(dec(q["strike"]).normalize())), []
                    ).append(q)
                fx_rate, fx_at, fx_source = _fx_asof(conn, str(snap["captured_at"]))
                cache[key] = (snap, by_strike, by_id, _policy(
                    allocated_eur=allocation, rate=fx_rate,
                    fx_at=fx_at, fx_source=fx_source,
                ))
            snap, qmap, by_id, policy = cache[key]
            if (str(snap["underlying"]) != idea.underlying
                or str(snap["captured_at"]) != idea.as_of):
                result.extend(_missing(idea, sid, "SOURCE_SNAPSHOT_IDENTITY_MISMATCH",
                                       snapshot_id) for sid in OPTION_ONLY_FAMILIES)
                continue
            primary = (LEGACY_REVERSE_ID if "REVERSE" in
                       str(idea.structure_id or "").upper() else "S08")
            for sid in (*[s for s in OPTION_ONLY_FAMILIES if s != "S08"], primary):
                result.append(_evaluate_one(idea, sid, snap, qmap, by_id, policy))
        # Different ideas may repeat exact strike packages; this is a research
        # view of a bounded snapshot, not independent observations of edge.
        return tuple(result)
    finally:
        conn.close()
