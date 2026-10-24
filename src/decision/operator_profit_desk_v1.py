"""Single operator contract for the trading dashboard.

The latest historic butterfly proposal counts are *diagnostics*, never trade
recommendations. Only the shared unified ranker can populate a candidate for
manual broker re-quote. A model ranking without verified provenance stays NO
TRADE. No side-effecting DB operations or model-based profit claims here.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Sequence

from src.decision.opportunity import (
    OpportunityAssessment, VERDICT_MARGINAL, VERDICT_SKIP, VERDICT_WORTH,
)
from src.decision.trade_ideas import TradeIdea
from src.decision.unified_trade_ranker_v1 import (
    MANUAL_REQUOTE, MarketDecision, RankedOpportunity,
)

VERSION = "OPERATOR_PROFIT_DESK_V1"
MAX_QUOTE_AGE = timedelta(minutes=15)
MAX_SOURCE_SNAPSHOTS = 64


@dataclass(frozen=True)
class UnderlyingSourceCoverage:
    research_run_id: int | None
    sampled_snapshots: int
    independent_fresh_prices: int
    state: str
    rejected_reasons: tuple[tuple[str, int], ...] = ()
    capture_attempts: int = 0
    prospective_decisions_frozen: int = 0
    capture_failures: int = 0


def load_underlying_source_coverage(*, db_path=None) -> UnderlyingSourceCoverage:
    """Lightweight current-run source health, NOT an expiry outcome.

    Identical independent provider identity and 15-second source clock as the
    seven-family discovery gate. No full historical scan or DB writes.
    """
    from src.operations.sqlite_runtime import open_readonly_connection
    from src.research.massive_underlying_observation_v1 import (
        MAX_AGE_SECONDS, STOCK_PRICE_SOURCE,
    )
    conn = open_readonly_connection(db_path)
    try:
        run = conn.execute(
            "SELECT id FROM research_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if run is None:
            return UnderlyingSourceCoverage(None, 0, 0, "NO_COMPLETED_RUN")
        run_id = int(run["id"])
        rows = conn.execute(
            """SELECT captured_at,underlying_at,underlying_price,
                      underlying_source,notes
               FROM market_snapshots
               WHERE research_run_id=? AND provider='THETADATA'
               ORDER BY id LIMIT ?""",
            (run_id, MAX_SOURCE_SNAPSHOTS + 1),
        ).fetchall()
        if len(rows) > MAX_SOURCE_SNAPSHOTS:
            return UnderlyingSourceCoverage(
                run_id, len(rows), 0, "SOURCE_COUNT_ABOVE_SAFE_BOUND"
            )
        eligible = 0
        rejected = Counter()
        for row in rows:
            note = str(row["notes"] or "")
            origin = note.partition("source_disposition=")[2]
            stated_reason = (
                origin.split(".", 1)[0].split(";", 1)[0].strip()
                if origin else ""
            )
            reason = stated_reason or "LEGACY_NO_REJECTION_REASON"
            if (
                row["underlying_price"] is None
                or row["underlying_source"] != "FETCHED"
                or f"stock price source={STOCK_PRICE_SOURCE};" not in note
            ):
                rejected[reason] += 1
                continue
            try:
                if float(row["underlying_price"]) <= 0:
                    rejected["INVALID_INDEPENDENT_STOCK_PRICE"] += 1
                    continue
                captured = datetime.fromisoformat(
                    str(row["captured_at"]).replace("Z", "+00:00")
                )
                source = datetime.fromisoformat(
                    str(row["underlying_at"]).replace("Z", "+00:00")
                )
                if captured.tzinfo is None or source.tzinfo is None:
                    rejected["MISSING_AWARE_SOURCE_TIMESTAMP"] += 1
                    continue
                age = (captured - source).total_seconds()
                if 0 <= age <= MAX_AGE_SECONDS:
                    eligible += 1
                else:
                    rejected["SOURCE_OUTSIDE_15_SECOND_CUT"] += 1
            except (ValueError, TypeError, OverflowError):
                rejected["INVALID_INDEPENDENT_SOURCE_FIELD"] += 1
        capture = conn.execute(
            """SELECT COUNT(*) AS attempts,
                      COALESCE(SUM(decisions_frozen),0) AS frozen_count,
                      COALESCE(SUM(state='CAPTURE_FAILURE'),0) AS failures
               FROM unified_capture_dispositions_v1
               WHERE research_run_id=?""",
            (run_id,),
        ).fetchone()
        return UnderlyingSourceCoverage(
            run_id, len(rows), eligible,
            "SOURCED" if eligible else "NO_INDEPENDENT_STOCK_PRICES",
            tuple(sorted(rejected.items(), key=lambda v: (-v[1], v[0]))),
            capture_attempts=int(capture["attempts"]),
            prospective_decisions_frozen=int(capture["frozen_count"]),
            capture_failures=int(capture["failures"]),
        )
    finally:
        conn.close()


@dataclass(frozen=True)
class LegacyNearMiss:
    underlying: str
    expiration: str
    structure: str
    proposed_max_loss_usd: float | None
    model_net_edge_usd: float | None
    reason: str
    estimated_model_agreement: int
    reference_snapshot_at: str | None


@dataclass(frozen=True)
class TradingDeskState:
    verdict: str
    explanation: str
    latest_session: str | None
    latest_snapshot_at: str | None
    source_fresh: bool
    promotable_trades: int
    research_proposals_reviewed: int
    research_legacy_skip: int
    research_legacy_marginal: int
    research_legacy_worth: int
    no_trade_reasons: tuple[tuple[str, int], ...]
    ranked_candidates: tuple[RankedOpportunity, ...]
    legacy_near_misses: tuple[LegacyNearMiss, ...]
    authority: str = "NONE"


def _fresh_utc(raw: str | None, now: datetime) -> bool:
    if not raw:
        return False
    try:
        instant = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if instant.tzinfo is None:
            return False
        seconds = (now - instant.astimezone(UTC)).total_seconds()
        return 0 <= seconds <= MAX_QUOTE_AGE.total_seconds()
    except (TypeError, ValueError):
        return False


def build_trading_desk_state(
    existing: Sequence[tuple[TradeIdea, OpportunityAssessment]],
    *,
    latest_session: str | None,
    authoritative: MarketDecision | None = None,
    authoritative_latest_snapshot_at: str | None = None,
    now: datetime | None = None,
) -> TradingDeskState:
    """One actionable stream; historical scanner votes cannot bypass it."""
    now = now or datetime.now(UTC)
    legacy_snapshot = max(
        (idea.as_of for idea, _ in existing if idea.as_of), default=None,
    )
    last_snapshot = authoritative_latest_snapshot_at or legacy_snapshot
    source_fresh = _fresh_utc(last_snapshot, now)
    counts = Counter(assessment.verdict for _, assessment in existing)
    diagnostic_reasons = Counter(
        assessment.reason_code or "UNSCORABLE" for _, assessment in existing
    )
    eligible: list[RankedOpportunity] = []
    if authoritative is not None:
        for row in authoritative.opportunities:
            if row.state == MANUAL_REQUOTE:
                eligible.append(row)
    # Historical proposal model scores cannot be promoted under any condition.
    blockers = Counter(diagnostic_reasons)
    if authoritative is None:
        blockers["UNIFIED_PROSPECTIVE_TRADE_RANKING_NOT_CONNECTED"] += 1
    elif not eligible:
        blockers["NO_UNIFIED_CANDIDATE_PASSED_ALL_PROOF_AND_COST_GATES"] += 1
        for row in authoritative.opportunities:
            blockers.update(row.missing_evidence)
    if not source_fresh:
        blockers["NO_CURRENT_EXECUTABLE_MARKET_SNAPSHOT"] += 1
        eligible = []

    # Guard an invalid upstream verdict as well: manual review is NEVER
    # equivalent to a broker-executable order or a proven profitable trade.
    ranked = sorted(
        eligible,
        key=lambda row: (row.rank is None, row.rank or 9999),
    )
    near_misses = [
        LegacyNearMiss(
            underlying=idea.underlying,
            expiration=idea.expiration,
            structure=idea.structure_id or "Unknown structure",
            proposed_max_loss_usd=idea.max_loss_usd,
            model_net_edge_usd=assessment.net_edge_usd,
            reason=assessment.reason_code or "Unknown",
            estimated_model_agreement=assessment.models_favouring,
            reference_snapshot_at=idea.as_of,
        )
        for idea, assessment in existing[:3]
    ]
    # Even an 'eligible' computed row always needs a fresh broker re-quote.
    if ranked:
        verdict = "CANDIDATES FOR MANUAL REQUOTE"
        explanation = (
            "Model-screened opportunities exist, but the prices are not broker "
            "orders or independently demonstrated trading profits."
        )
    else:
        verdict = "NO TRADE"
        if not source_fresh:
            explanation = (
                "No current, executable market snapshot supports a trade. "
                "Historical research candidates cannot substitute for live evidence."
            )
        elif authoritative is None:
            explanation = (
                "The unified profitability engine has no qualified prospective "
                "forecast/result stream yet. Legacy price discrepancies are not trades."
            )
        else:
            explanation = (
                "No structure beats doing nothing under the common evidence, "
                "cost, disagreement and risk checks."
            )
    return TradingDeskState(
        verdict=verdict, explanation=explanation,
        latest_session=latest_session, latest_snapshot_at=last_snapshot,
        source_fresh=source_fresh,
        promotable_trades=len(ranked),
        research_proposals_reviewed=len(existing),
        research_legacy_skip=counts[VERDICT_SKIP],
        research_legacy_marginal=counts[VERDICT_MARGINAL],
        research_legacy_worth=counts[VERDICT_WORTH],
        no_trade_reasons=tuple(sorted(
            ((str(k), int(v)) for k, v in blockers.items()),
            key=lambda item: (-item[1], item[0]),
        )),
        ranked_candidates=tuple(ranked),
        legacy_near_misses=tuple(near_misses),
    )
