"""Opportunity assessment: one honest confidence score per proposed trade.

What this is
------------
The three fits (line, curve, smile) all read the same quotes, so their
agreement is weak evidence (see the 2026-10-17 verification).  This module does
*not* add them up.  It asks a different question:

    After costs, is the apparent mispricing clearly bigger than the noise in
    the quotes that produced it?

score = net edge after costs / (dollar value of the quote uncertainty)

    = (net / gross) * (|fair IV - market IV| / sigma_total)

* ``net / gross`` is the share of the gross edge that survives the spread and
  the fees.  It is negative when costs exceed the edge.
* ``sigma_total`` combines a *bid/ask-only* quote uncertainty model with
  dispersion between fits that share the same quotes. Neither measures latent
  midpoint error, stale quote variation, or full fair-IV estimation error.
  The quoted spread is converted to a uniform width/sqrt(12) IV uncertainty
  through option vega and chord wing weights. This is an *incomplete* proxy,
  not a calibrated two-sigma confidence statement.

Nothing here is fitted to outcomes.  The thresholds below are fixed *a priori*
(two sigma is the conventional bar for "clearly bigger than noise"); whether
they select better trades than chance is measured separately, prospectively,
against a matched placebo (see ``opportunity_evidence``).  Until that
evidence exists every verdict is a suggestion to look, not a result.

Pure functions only: no database, no network, no randomness.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from statistics import median, stdev
from typing import Any, Mapping, Sequence

from src.decision.trade_ideas import (
    IdeaLeg,
    MarketInputs,
    TradeIdea,
    judge_model,
    structure_fees_usd,
)
from src.quant.greeks import analytic as analytic_greeks
from src.quant.types import QuantInputError, VanillaOption

SCORING_VERSION = "OPP_V2"

# A priori design constants (never tuned on outcomes).
Z_WORTH = 2.0  # edge at least two noise-sigmas above zero after costs
Z_MARGINAL = 1.0
MIN_MODELS = 2  # model dispersion is undefined with fewer
MAX_SPREAD_TO_MID = 0.20  # same limit the scanner applies to any quote
PLACEBO_MAX_LOG_MONEYNESS = 0.10

VERDICT_WORTH = "WORTH A LOOK"
VERDICT_MARGINAL = "MARGINAL"
VERDICT_SKIP = "SKIP"
VERDICT_PLACEBO = "PLACEBO"
VERDICT_RANK = {VERDICT_WORTH: 0, VERDICT_MARGINAL: 1, VERDICT_SKIP: 2}

HEADLINES = {
    "WORTH": "Estimated edge exceeds spread-derived and historical quote-IV variation proxies after assumed costs; latent midpoint noise and real profitability remain unverified.",
    "MARGINAL": "Estimated edge exceeds modeled costs but remains near spread-derived uncertainty; not a verified opportunity.",
    "WITHIN_NOISE": "The price gap is within the noise of the quotes.",
    "COSTS_EAT_EDGE": "Costs eat the edge: the price gap is smaller than the cost of trading it.",
    "NO_EDGE": "The models do not see this structure as underpriced.",
    "QUOTES_INCONSISTENT": "The quotes do not match their own implied volatility; the gap is likely a data artefact.",
    "TOO_FEW_MODELS": "Fewer than two models could judge this trade.",
    "NO_INPUTS": "Not enough data to judge this trade.",
    "UNVERIFIED_QUOTE_VARIATION": "A model price gap is present, but there is insufficient independent-in-time quote history to verify that it exceeds ordinary market-IV variation. Check live quotes before acting.",
    "AMERICAN_PUT_IV_UNVERIFIED": "The put IV model has not been verified for American exercise; do not treat this score as an executable advantage.",
}


@dataclass(frozen=True)
class OpportunityAssessment:
    verdict: str
    reason_code: str
    headline: str
    score: float | None
    net_edge_usd: float | None
    gross_edge_usd: float | None
    fair_iv: float | None
    market_iv: float | None
    residual_vol_pts: float | None
    sigma_quote_vol_pts: float | None
    sigma_model_vol_pts: float | None
    models_available: int
    models_favouring: int
    features: Mapping[str, Any] = field(default_factory=dict)


def leg_iv_sigma(leg: IdeaLeg, market: MarketInputs) -> float:
    """Standard deviation (in IV units, 0.01 = one vol point) of the IV implied
    by one quote that is only known to lie between its bid and ask."""
    width = max(leg.ask - leg.bid, 0.0)
    try:
        vega = analytic_greeks(
            VanillaOption(
                spot=market.spot,
                strike=leg.strike,
                time_to_expiry=market.t_years,
                rate=market.rate,
                volatility=leg.market_iv,
                right="CALL" if str(leg.right).upper().startswith("C") else "PUT",
                dividend_yield=market.dividend_yield,
            )
        ).vega
    except (QuantInputError, ValueError, ZeroDivisionError):
        return math.inf
    if not math.isfinite(vega) or vega <= 1e-9:
        return math.inf
    return width / (math.sqrt(12.0) * vega)


def _skip(code: str, *, models_available: int = 0, features: Mapping[str, Any] | None = None) -> OpportunityAssessment:
    return OpportunityAssessment(
        verdict=VERDICT_SKIP,
        reason_code=code,
        headline=HEADLINES[code],
        score=None,
        net_edge_usd=None,
        gross_edge_usd=None,
        fair_iv=None,
        market_iv=None,
        residual_vol_pts=None,
        sigma_quote_vol_pts=None,
        sigma_model_vol_pts=None,
        models_available=models_available,
        models_favouring=0,
        features=dict(features or {}),
    )


def assess_idea(
    idea: TradeIdea,
    *,
    historical_iv_sigma_by_quote_id: Mapping[int, float] | None = None,
    historical_iv_samples_by_quote_id: Mapping[int, int] | None = None,
) -> OpportunityAssessment:
    """Pure assessment; stronger verdicts require as-of prior-quote variation.

    A spread-only model cannot measure latent midpoint errors. Repeated
    historical quotes provide a conservative but imperfect IV variation proxy,
    not independent-vendor evidence or a promise of profitable execution.
    """
    market = idea.market
    legs = idea.legs
    target = idea.target_strike
    if market is None or not legs or idea.max_loss_usd is None:
        return _skip("NO_INPUTS")

    available = [
        j for j in idea.judgements.values()
        if j.available and target in j.fair_iv_by_strike
    ]
    if len(available) < MIN_MODELS:
        inconsistent = any(
            (not j.available) and str(j.reason or "").startswith("Quotes inconsistent")
            for j in idea.judgements.values()
        )
        return _skip(
            "QUOTES_INCONSISTENT" if inconsistent else "TOO_FEW_MODELS",
            models_available=len(available),
        )

    fairs = [float(j.fair_iv_by_strike[target]) for j in available]
    fair = float(median(fairs))
    sigma_model = float(stdev(fairs)) if len(fairs) >= 2 else 0.0

    target_leg = next((l for l in legs if l.strike == target), None)
    strikes = sorted({l.strike for l in legs})
    if target_leg is None or len(strikes) != 3 or strikes[1] != target:
        return _skip("NO_INPUTS", models_available=len(available))
    lower = next(l for l in legs if l.strike == strikes[0])
    upper = next(l for l in legs if l.strike == strikes[2])
    span = strikes[2] - strikes[0]
    w_lo = (strikes[2] - target) / span
    w_hi = (target - strikes[0]) / span

    sig_t = leg_iv_sigma(target_leg, market)
    sig_lo = leg_iv_sigma(lower, market)
    sig_hi = leg_iv_sigma(upper, market)
    sigma_quote = math.sqrt(sig_t**2 + (w_lo * sig_lo) ** 2 + (w_hi * sig_hi) ** 2)
    by_quote = historical_iv_sigma_by_quote_id or {}
    by_samples = historical_iv_samples_by_quote_id or {}
    calibrated = all(
        l.option_quote_id in by_quote
        and math.isfinite(float(by_quote[l.option_quote_id]))
        and float(by_quote[l.option_quote_id]) >= 0
        and int(by_samples.get(l.option_quote_id, 0)) >= 6
        for l in (target_leg, lower, upper)
    )
    sigma_history = (
        math.sqrt(
            float(by_quote[target_leg.option_quote_id]) ** 2
            + (w_lo * float(by_quote[lower.option_quote_id])) ** 2
            + (w_hi * float(by_quote[upper.option_quote_id])) ** 2
        )
        if calibrated else None
    )
    sigma_total = math.sqrt(
        sigma_quote**2 + sigma_model**2
        + (sigma_history**2 if sigma_history is not None else 0.0)
    )

    combined = judge_model(
        "OPP_COMBINED", legs, market, {target: fair}, max_loss_usd=float(idea.max_loss_usd)
    )
    resid = fair - float(target_leg.market_iv)
    spreads = [
        (l.ask - l.bid) / l.mid if l.mid > 0 else math.inf for l in legs
    ]
    features: dict[str, Any] = {
        "dte": idea.dte,
        "log_moneyness": math.log(target / market.spot) if market.spot > 0 else None,
        "atm_iv": idea.profile.atm_iv if idea.profile else None,
        "fair_ivs": {j.model_id: float(j.fair_iv_by_strike[target]) for j in available},
        "model_net_edges_usd": {j.model_id: j.net_edge_usd for j in available},
        "max_spread_to_mid": max(spreads) if spreads else None,
        "spread_to_mid_by_leg": {f"{l.strike:g}": s for l, s in zip(legs, spreads)},
        "sigma_target_vol_pts": sig_t * 100.0,
        "sigma_wing_lo_vol_pts": sig_lo * 100.0,
        "sigma_wing_hi_vol_pts": sig_hi * 100.0,
        "fees_usd": structure_fees_usd(legs),
        "direction": idea.anomaly_direction,
        "spread_only_sigma_vol_pts": sigma_quote * 100 if math.isfinite(sigma_quote) else None,
        "quote_uncertainty_basis": (
            "BID_ASK_WIDTH_AND_PRIOR_IV_VARIATION_PROXY"
            if calibrated else "BID_ASK_WIDTH_UNIFORM_ONLY"
        ),
        "historical_iv_variation_calibrated": calibrated,
        "historical_iv_variation_sigma_vol_pts": (
            sigma_history * 100 if sigma_history is not None else None
        ),
        "historical_iv_sigma_by_quote_id": (
            {str(l.option_quote_id): float(by_quote[l.option_quote_id])
             for l in (target_leg, lower, upper)}
            if calibrated else {}
        ),
        "historical_iv_variation_samples_by_quote_id": (
            {str(l.option_quote_id): int(by_samples[l.option_quote_id])
             for l in (target_leg, lower, upper)}
            if calibrated else {}
        ),
        "independent_vendor_confirmation": False,
        "latent_midpoint_noise_measured": False,
        "model_fit_independence_assumed": False,
        "prospective_profitability_proven": False,
    }
    common = dict(
        fair_iv=fair,
        market_iv=float(target_leg.market_iv),
        residual_vol_pts=resid * 100.0,
        sigma_quote_vol_pts=(
            math.sqrt(sigma_quote ** 2 + (sigma_history or 0.0) ** 2) * 100.0
            if math.isfinite(sigma_quote) else None
        ),
        sigma_model_vol_pts=sigma_model * 100.0,
        models_available=len(available),
        models_favouring=sum(1 for j in available if j.favours),
        features=features,
    )
    if not combined.available:
        return _skip("QUOTES_INCONSISTENT", models_available=len(available), features=features)

    gross = float(combined.gross_edge_usd)
    net = float(combined.net_edge_usd)
    score: float | None = None
    if abs(resid) > 1e-9 and math.isfinite(sigma_total) and sigma_total > 0:
        usd_per_iv = abs(gross) / abs(resid)
        score = net / (usd_per_iv * sigma_total) if usd_per_iv > 0 else None

    def build(verdict: str, code: str) -> OpportunityAssessment:
        return OpportunityAssessment(
            verdict=verdict,
            reason_code=code,
            headline=HEADLINES[code],
            score=score,
            net_edge_usd=net,
            gross_edge_usd=gross,
            **common,
        )

    if gross <= 0.0:
        return build(VERDICT_SKIP, "NO_EDGE")
    if net <= 0.0:
        return build(VERDICT_SKIP, "COSTS_EAT_EDGE")
    if score is None or score < Z_MARGINAL:
        return build(VERDICT_SKIP, "WITHIN_NOISE")
    if score < Z_WORTH:
        return build(VERDICT_MARGINAL, "MARGINAL")
    if not calibrated:
        return build(VERDICT_MARGINAL, "UNVERIFIED_QUOTE_VARIATION")
    if str(idea.right).upper().startswith("P"):
        return build(VERDICT_MARGINAL, "AMERICAN_PUT_IV_UNVERIFIED")
    return build(VERDICT_WORTH, "WORTH")


def rank_by_opportunity(
    ideas: Sequence[TradeIdea],
    *,
    prior_noise_by_proposal: Mapping[int, tuple[Mapping[int, float], Mapping[int, int]]] | None = None,
) -> list[tuple[TradeIdea, OpportunityAssessment]]:
    """One consistent as-of persisted score on UI and in research cycle."""
    calibrated = prior_noise_by_proposal or {}
    pairs = []
    for idea in ideas:
        iv_sigmas, samples = calibrated.get(idea.proposal_id, ({}, {}))
        pairs.append((
            idea,
            assess_idea(
                idea,
                historical_iv_sigma_by_quote_id=iv_sigmas,
                historical_iv_samples_by_quote_id=samples,
            ),
        ))

    def key(pair):
        idea, a = pair
        return (
            VERDICT_RANK[a.verdict],
            -(a.score if a.score is not None else float("-inf")),
            idea.underlying,
        )

    return sorted(pairs, key=key)


# --------------------------------------------------------------------------
# Matched placebo
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class ChainQuote:
    option_quote_id: int
    strike: float
    bid: float
    ask: float
    iv: float
    multiplier: float


def _usable(q: ChainQuote) -> bool:
    if not (math.isfinite(q.bid) and math.isfinite(q.ask) and q.bid > 0 and q.ask > q.bid):
        return False
    mid = (q.bid + q.ask) / 2.0
    return (q.ask - q.bid) / mid <= MAX_SPREAD_TO_MID and q.iv > 0


def build_placebo_legs(
    idea: TradeIdea,
    chain: Sequence[ChainQuote],
    *,
    seed: int,
) -> tuple[IdeaLeg, ...] | None:
    """Same butterfly shape, same direction, same snapshot, random centre.

    The centre is drawn uniformly from strikes that pass the same quote-quality
    limit as any real candidate, whose wings exist at the signal's own widths,
    within PLACEBO_MAX_LOG_MONEYNESS of spot, excluding the signal's centre.
    Entry is priced exactly like a real proposal (buy at ask, sell at bid).
    Returns None when no eligible centre exists (the idea then has no placebo,
    which the evaluation reports rather than hides).
    """
    if idea.market is None or len(idea.legs) != 3:
        return None
    ordered = sorted(idea.legs, key=lambda l: l.strike)
    lo_leg, mid_leg, hi_leg = ordered
    lo_w = mid_leg.strike - lo_leg.strike
    hi_w = hi_leg.strike - mid_leg.strike
    by_strike = {round(q.strike, 6): q for q in chain if _usable(q)}
    spot = idea.market.spot
    candidates: list[tuple[ChainQuote, ChainQuote, ChainQuote]] = []
    for key in sorted(by_strike):
        centre = by_strike[key]
        if abs(centre.strike - idea.target_strike) < 1e-9:
            continue
        if abs(math.log(centre.strike / spot)) > PLACEBO_MAX_LOG_MONEYNESS:
            continue
        lo_q = by_strike.get(round(centre.strike - lo_w, 6))
        hi_q = by_strike.get(round(centre.strike + hi_w, 6))
        if lo_q is None or hi_q is None:
            continue
        candidates.append((lo_q, centre, hi_q))
    if not candidates:
        return None
    lo_q, c_q, hi_q = random.Random(int(seed)).choice(candidates)
    mapped = {id(lo_leg): lo_q, id(mid_leg): c_q, id(hi_leg): hi_q}
    out: list[IdeaLeg] = []
    for leg in idea.legs:
        q = mapped[id(leg)]
        buy = leg.side.upper() == "BUY"
        out.append(
            IdeaLeg(
                option_quote_id=q.option_quote_id,
                right=leg.right,
                strike=q.strike,
                side=leg.side,
                quantity=leg.quantity,
                multiplier=q.multiplier,
                entry_price=q.ask if buy else q.bid,
                bid=q.bid,
                ask=q.ask,
                market_iv=q.iv,
            )
        )
    return tuple(out)
