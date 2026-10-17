"""Does the opportunity score find better trades than chance?

The only test that matters, defined *before* any outcome exists:

    Primary question (the single pre-registered test)
        For ideas the score called "WORTH A LOOK", is the paired excess
        net P&L  (signal - matched placebo)  greater than zero?

The placebo is the same butterfly shape and direction, on the same snapshot,
at a randomly chosen centre strike (see ``build_placebo_legs``).  Pairing
cancels everything the two share: market drift, volatility regime, the
terminal price, costs.  What remains is whether the *choice of strike* carried
information.

Statistical safeguards
* One bet counted once: ideas sharing (underlying, expiry, right, target
  strike, structure) are the same bet seen in several 15-minute slots.
* Dependence: bets expiring on the same date share a terminal market move, so
  the confidence interval resamples whole expiry dates (cluster bootstrap),
  not individual bets.
* Sample floors: no claim below MIN_BETS bets across MIN_DATES expiry dates.
* Secondary buckets (marginal, skip) and the rank correlation are reported
  descriptively and never used to declare success.

Nothing here can say "proven".  The strongest state is EVIDENCE_OF_EDGE, which
means: on paper, with assumed costs, over this sample, the lower end of the
interval is above zero.  Closing prices are last stored samples, not
settlement prices.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

import numpy as np
from scipy.stats import spearmanr

from src.decision.opportunity import (
    VERDICT_MARGINAL,
    VERDICT_SKIP,
    VERDICT_WORTH,
)

MIN_BETS = 30
MIN_DATES = 10
BOOTSTRAP_SAMPLES = 4000
BOOTSTRAP_SEED = 20261017
CONFIDENCE = 0.95

STATE_NO_DATA = "NO_DATA"
STATE_TOO_EARLY = "TOO_EARLY"
STATE_NOT_BETTER = "NOT_BETTER_THAN_CHANCE"
STATE_EVIDENCE = "EVIDENCE_OF_EDGE"


@dataclass(frozen=True)
class BucketStats:
    verdict: str
    bets: int
    expiry_dates: int
    mean_net_usd: float | None
    mean_placebo_net_usd: float | None
    mean_excess_usd: float | None


@dataclass(frozen=True)
class EvidenceReport:
    state: str
    headline: str
    primary_bets: int
    primary_expiry_dates: int
    primary_excess_usd: float | None
    primary_ci_usd: tuple[float, float] | None
    placebo_mean_net_usd: float | None
    bets_without_placebo: int
    rank_correlation: float | None
    buckets: tuple[BucketStats, ...] = field(default_factory=tuple)


def _dedupe(rows: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    seen: set[tuple] = set()
    out = []
    for row in sorted(rows, key=lambda r: int(r["proposal_id"])):
        if row["bet_key"] in seen:
            continue
        seen.add(row["bet_key"])
        out.append(row)
    return out


def cluster_bootstrap_ci(
    values: Sequence[float],
    clusters: Sequence[str],
    *,
    samples: int = BOOTSTRAP_SAMPLES,
    seed: int = BOOTSTRAP_SEED,
    confidence: float = CONFIDENCE,
) -> tuple[float, float] | None:
    """Percentile CI of the mean, resampling whole clusters with replacement."""
    if len(values) < 2:
        return None
    groups: dict[str, list[float]] = {}
    for v, c in zip(values, clusters):
        groups.setdefault(str(c), []).append(float(v))
    keys = sorted(groups)
    if len(keys) < 2:
        return None
    sums = np.array([sum(groups[k]) for k in keys], dtype=float)
    counts = np.array([len(groups[k]) for k in keys], dtype=float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(keys), size=(samples, len(keys)))
    means = sums[idx].sum(axis=1) / counts[idx].sum(axis=1)
    alpha = (1.0 - confidence) / 2.0
    return float(np.quantile(means, alpha)), float(np.quantile(means, 1.0 - alpha))


def _bucket(verdict: str, rows: Sequence[Mapping[str, Any]]) -> BucketStats:
    mine = [r for r in rows if r["verdict"] == verdict]
    paired = [r for r in mine if r["placebo_net"] is not None]
    return BucketStats(
        verdict=verdict,
        bets=len(mine),
        expiry_dates=len({r["expiration"] for r in mine}),
        mean_net_usd=(float(np.mean([r["signal_net"] for r in mine])) if mine else None),
        mean_placebo_net_usd=(float(np.mean([r["placebo_net"] for r in paired])) if paired else None),
        mean_excess_usd=(
            float(np.mean([r["signal_net"] - r["placebo_net"] for r in paired])) if paired else None
        ),
    )


def evaluate(rows: Sequence[Mapping[str, Any]]) -> EvidenceReport:
    """rows: one per resolved assessed idea with keys proposal_id, bet_key,
    expiration, verdict, score, signal_net, placebo_net (None if no placebo)."""
    bets = _dedupe(rows)
    buckets = tuple(_bucket(v, bets) for v in (VERDICT_WORTH, VERDICT_MARGINAL, VERDICT_SKIP))
    paired_all = [r for r in bets if r["placebo_net"] is not None]
    without = len(bets) - len(paired_all)
    placebo_mean = (
        float(np.mean([r["placebo_net"] for r in paired_all])) if paired_all else None
    )

    rank_corr = None
    scored = [r for r in paired_all if r.get("score") is not None]
    if len(scored) >= 10:
        excess = [r["signal_net"] - r["placebo_net"] for r in scored]
        if len(set(excess)) > 1 and len({r["score"] for r in scored}) > 1:
            rho = spearmanr([r["score"] for r in scored], excess).statistic
            rank_corr = float(rho) if math.isfinite(rho) else None

    primary = [r for r in paired_all if r["verdict"] == VERDICT_WORTH]
    dates = {r["expiration"] for r in primary}
    excess_vals = [r["signal_net"] - r["placebo_net"] for r in primary]
    excess_mean = float(np.mean(excess_vals)) if excess_vals else None

    def report(state: str, headline: str, ci=None) -> EvidenceReport:
        return EvidenceReport(
            state=state,
            headline=headline,
            primary_bets=len(primary),
            primary_expiry_dates=len(dates),
            primary_excess_usd=excess_mean,
            primary_ci_usd=ci,
            placebo_mean_net_usd=placebo_mean,
            bets_without_placebo=without,
            rank_correlation=rank_corr,
            buckets=buckets,
        )

    if not bets:
        return report(STATE_NO_DATA, "No finished trades to judge yet.")
    if len(primary) < MIN_BETS or len(dates) < MIN_DATES:
        return report(
            STATE_TOO_EARLY,
            f"Too early to tell: {len(primary)} of {MIN_BETS} needed 'worth a look' trades "
            f"finished, on {len(dates)} of {MIN_DATES} needed expiry dates.",
        )
    ci = cluster_bootstrap_ci(excess_vals, [r["expiration"] for r in primary])
    if ci is None:
        return report(STATE_TOO_EARLY, "Too early to tell: not enough independent expiry dates.")
    if ci[0] > 0.0:
        return report(
            STATE_EVIDENCE,
            "Evidence of an edge on paper: 'worth a look' trades beat the random-strike placebo "
            "after assumed costs. Still not proof for real money.",
            ci,
        )
    return report(
        STATE_NOT_BETTER,
        "No evidence yet that 'worth a look' trades beat random strikes after costs.",
        ci,
    )
