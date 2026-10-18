"""Deterministic synthetic null controls for opportunity scores.

Not Claude's lost 2026-10-17 prove.py. Independent conservative miniature:
all contracts have a common latent flat 25% volatility, but one captured
quote snapshot has independent IV measurement errors. The three fair-value
judgements re-use the same noisy wing quotes, so agreement is NOT a second
measurement. These simulations are NOT proof of a trading strategy.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import NamedTuple

from src.decision.opportunity import VERDICT_MARGINAL, VERDICT_WORTH, assess_idea
from src.decision.trade_ideas import (
    IdeaLeg, MarketInputs, ModelJudgement, TradeIdea, _bs,
)


class NullStats(NamedTuple):
    noise_iv: float
    observations: int
    worth: int
    marginal_or_worth: int
    max_score: float | None


def run_null(
    *, noise_iv: float, n: int = 600, seed: int = 20261017,
    half_spread_usd: float = 0.03,
) -> NullStats:
    """Every idea originates in quote noise, not a true structured IV edge.

    Does not fabricate realized P&L. The null truth is a flat IV surface,
    with static + correlated fit errors arising from shared noisy quotes.
    """
    if not (0 <= noise_iv <= 0.1 and n > 0 and half_spread_usd > 0):
        raise ValueError("invalid null-world parameters")
    rng = random.Random(seed)
    market = MarketInputs(100.0, 60.0 / 365, 0.04, 0.0, True)
    strikes = (95.0, 100.0, 105.0)
    worth = marginal_or_worth = 0
    top = None
    for i in range(n):
        iv = [max(0.05, 0.25 + rng.gauss(0, noise_iv)) for _ in strikes]
        wing_fair = (iv[0] + iv[2]) / 2.0
        target_is_cheap = iv[1] < wing_fair
        legs = []
        for idx, (strike, quoted_iv) in enumerate(zip(strikes, iv)):
            mid = _bs(market, strike, quoted_iv, "C")
            # Bid and ask are symmetrically placed around the noisy midpoint.
            bid = mid - half_spread_usd
            ask = mid + half_spread_usd
            assert bid > 0.0
            side = ("BUY" if idx == 1 else "SELL") if target_is_cheap else (
                "SELL" if idx == 1 else "BUY"
            )
            legs.append(IdeaLeg(
                option_quote_id=i * 3 + idx + 1,
                right="C", strike=strike, side=side,
                quantity=2 if idx == 1 else 1,
                multiplier=100.0,
                entry_price=ask if side == "BUY" else bid,
                bid=bid, ask=ask, market_iv=quoted_iv,
            ))
        # All models share wing inputs. Their near agreement carries no
        # statistical independence and cannot establish a real edge.
        judgements = {
            f"FIT_{j}": ModelJudgement(
                model_id=f"FIT_{j}", available=True, verdict="EDGE",
                fair_iv_by_strike={strikes[1]: wing_fair + offset},
            )
            for j, offset in enumerate((-0.0001, 0.0, 0.0001))
        }
        idea = TradeIdea(
            proposal_id=i + 1, research_run_id=1, underlying="SYNTHETIC",
            expiration="2026-12-18", right="C", structure_id=None,
            anomaly_direction="CHEAP" if target_is_cheap else "RICH",
            target_strike=100.0, strikes=strikes, dte=60,
            session_date="2026-10-18", as_of="2026-10-18T14:00:00Z",
            spot=100.0, net_debit_usd=None, max_loss_usd=1000.0,
            fees_usd=None, profile=None, judgements=judgements,
            favouring=3, available=3, median_net_edge_usd=None,
            median_net_edge_to_max_loss=None,
            admission_decision=None, admission_reason=None,
            candidate_id=None, legs=tuple(legs), market=market,
        )
        assessment = assess_idea(idea)
        worth += assessment.verdict == VERDICT_WORTH
        marginal_or_worth += assessment.verdict in (VERDICT_WORTH, VERDICT_MARGINAL)
        if assessment.score is not None:
            top = max(top, assessment.score) if top is not None else assessment.score
    return NullStats(noise_iv, n, worth, marginal_or_worth, top)


def test_no_quote_noise_never_finds_false_worth():
    zero = run_null(noise_iv=0.0, n=600)
    assert zero.worth == 0
    assert zero.marginal_or_worth == 0


def test_high_midpoint_noise_is_not_modelled_by_bid_ask_width():
    low = run_null(noise_iv=0.006)
    high = run_null(noise_iv=0.012)
    # The former spread-only model labelled 34/600 and 212/600 as WORTH
    # (at 0.006 and 0.012 noise, respectively). Without empirical prior quote
    # history, V2 now refuses to certify either as WORTH; the underlying
    # uncalibrated model gaps remain visible as marginal suggestions.
    assert low.worth == 0
    assert high.worth == 0
    assert high.marginal_or_worth > low.marginal_or_worth
    assert high.max_score is not None and high.max_score > 2


if __name__ == "__main__":
    import json
    for noise in (0.0, 0.006, 0.012):
        print(json.dumps(run_null(noise_iv=noise)._asdict(), sort_keys=True))
