"""Trade ideas: what several independent models say about each proposed trade.

Purpose
-------
Answer one question per current proposal: *does each model think this
structure is worth more than it costs to enter, after spread and fees?*

Design rules (deliberately conservative)
----------------------------------------
* Each model gives its **own** judgement. Nothing is blended into one score.
* A model judges a structure by re-pricing every leg at that model's fair
  implied volatility (market IV where the model has no opinion) and comparing
  with the market's IV-implied price. Only the difference is used, so
  rate / dividend / early-exercise basis cancels out of the edge.
* Costs are charged in full: crossing the bid/ask spread at the proposal's
  conservative entry prices, plus the same fee model the admission policy uses.
* "Chance of profit" is a **risk-neutral lognormal approximation at the
  at-the-money IV** -- an intuition aid about the profit zone, not a forecast.
  The empirical evidence is the track record, computed from resolved expiry
  outcomes, never from the models themselves.
* Nothing here is invented: if an input is missing the model is reported as
  unavailable with the reason, and there is no verdict.

The module is read-only with respect to the database.
"""
from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, time as dtime
from statistics import median
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

import numpy as np
from scipy.stats import norm

from src.database.repository import get_connection
from src.quant import svi as svi_model
from src.quant.black_scholes import price as bs_price
from src.quant.types import QuantInputError, VanillaOption
from src.research.shadow_intrinsic_admission_v1 import (
    USD_COST_PER_CONTRACT_SIDE_MINOR,
)
from src.research.shadow_lifecycle import GreekQuality, classify_greek_quality

NY = ZoneInfo("America/New_York")
DAYS_PER_YEAR = 365.0

MODEL_V1 = "V1_LINEAR_CHORD"
MODEL_V2 = "V2_QUADRATIC_LOO"
MODEL_SVI = "SVI_SMILE"
MODEL_ORDER = (MODEL_V1, MODEL_V2, MODEL_SVI)
MODEL_LABELS = {
    MODEL_V1: "Line fit",
    MODEL_V2: "Curve fit",
    MODEL_SVI: "Smile fit",
}

VERDICT_EDGE = "EDGE AFTER COSTS"
VERDICT_COSTS_EAT_EDGE = "EDGE EATEN BY COSTS"
VERDICT_AGAINST = "MODEL DISAGREES"
VERDICT_UNAVAILABLE = "UNAVAILABLE"


# --------------------------------------------------------------------------
# Plain inputs
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class IdeaLeg:
    option_quote_id: int
    right: str  # "C" or "P"
    strike: float
    side: str  # "BUY" or "SELL"
    quantity: int
    multiplier: float
    entry_price: float
    bid: float
    ask: float
    market_iv: float

    @property
    def sign(self) -> float:
        return 1.0 if self.side.upper() == "BUY" else -1.0

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0


@dataclass(frozen=True)
class MarketInputs:
    spot: float
    t_years: float
    rate: float
    dividend_yield: float
    rate_and_yield_stored: bool


# --------------------------------------------------------------------------
# Outputs
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class ModelJudgement:
    model_id: str
    available: bool
    verdict: str
    reason: str | None = None
    fair_iv_by_strike: Mapping[float, float] = field(default_factory=dict)
    gross_edge_usd: float | None = None
    spread_cost_usd: float | None = None
    fees_usd: float | None = None
    net_edge_usd: float | None = None
    net_edge_to_max_loss: float | None = None
    detail: Mapping[str, Any] = field(default_factory=dict)

    @property
    def favours(self) -> bool:
        return self.available and (self.net_edge_usd or 0.0) > 0.0


@dataclass(frozen=True)
class ProfitProfile:
    max_profit_usd: float
    max_loss_usd: float
    breakevens: tuple[float, ...]
    profit_intervals: tuple[tuple[float | None, float | None], ...]
    p_profit: float
    atm_iv: float
    expected_move_1sd: float


@dataclass(frozen=True)
class TradeIdea:
    proposal_id: int
    research_run_id: int
    underlying: str
    expiration: str
    right: str
    structure_id: str | None
    anomaly_direction: str
    target_strike: float
    strikes: tuple[float, ...]
    dte: int | None
    session_date: str | None
    as_of: str | None
    spot: float | None
    net_debit_usd: float | None  # >0 you pay, <0 you receive
    max_loss_usd: float | None
    fees_usd: float | None
    profile: ProfitProfile | None
    judgements: Mapping[str, ModelJudgement]
    favouring: int
    available: int
    median_net_edge_usd: float | None
    median_net_edge_to_max_loss: float | None
    admission_decision: str | None
    admission_reason: str | None
    candidate_id: int | None
    notes: tuple[str, ...] = ()
    legs: tuple[IdeaLeg, ...] = ()
    market: MarketInputs | None = None


# --------------------------------------------------------------------------
# Pure pricing helpers
# --------------------------------------------------------------------------
def _right_name(right: str) -> str:
    return "CALL" if str(right).upper().startswith("C") else "PUT"


def _bs(market: MarketInputs, strike: float, vol: float, right: str) -> float:
    return bs_price(
        VanillaOption(
            spot=market.spot,
            strike=float(strike),
            time_to_expiry=market.t_years,
            rate=market.rate,
            volatility=float(vol),
            right=_right_name(right),
            dividend_yield=market.dividend_yield,
        )
    )


def structure_fees_usd(legs: Sequence[IdeaLeg]) -> float:
    """Same fee model the admission policy applies: a fixed amount per
    contract side, charged both ways (conservative for hold-to-expiry)."""
    sides = sum(abs(int(leg.quantity)) for leg in legs)
    return sides * 2 * USD_COST_PER_CONTRACT_SIDE_MINOR / 100.0


def entry_cashflow_usd(legs: Sequence[IdeaLeg]) -> float:
    """Cash at entry: negative = you pay (debit), positive = you receive."""
    return sum(
        -leg.sign * leg.quantity * leg.multiplier * leg.entry_price
        for leg in legs
    )


def terminal_value_usd(legs: Sequence[IdeaLeg], underlying_price: float) -> float:
    total = 0.0
    for leg in legs:
        if _right_name(leg.right) == "CALL":
            intrinsic = max(underlying_price - leg.strike, 0.0)
        else:
            intrinsic = max(leg.strike - underlying_price, 0.0)
        total += leg.sign * leg.quantity * leg.multiplier * intrinsic
    return total


def quote_consistency_problem(
    legs: Sequence[IdeaLeg], market: MarketInputs
) -> str | None:
    """Return a reason if a leg's provider IV does not reproduce its own
    bid/ask.  Every model edge here is a difference of Black-Scholes prices, so
    if BS(provider IV) sits far outside the quoted market the IV, the spot, the
    time to expiry or the rate is wrong and any "edge" is an artefact.  The
    allowance is one quoted spread outside the band (no invented threshold)."""
    for leg in legs:
        try:
            px = _bs(market, leg.strike, leg.market_iv, leg.right)
        except (QuantInputError, ValueError, ZeroDivisionError) as exc:
            return f"Could not price {leg.strike:g} at its provider IV: {exc}"
        width = max(leg.ask - leg.bid, 0.0)
        if not math.isfinite(px) or px < leg.bid - width or px > leg.ask + width:
            return (
                f"Provider IV at strike {leg.strike:g} does not reproduce the "
                f"quote (model price {px:.2f} vs bid {leg.bid:.2f} / ask {leg.ask:.2f})."
            )
    return None


def judge_model(
    model_id: str,
    legs: Sequence[IdeaLeg],
    market: MarketInputs,
    fair_iv_by_strike: Mapping[float, float],
    *,
    max_loss_usd: float,
    detail: Mapping[str, Any] | None = None,
) -> ModelJudgement:
    """Judge one structure for one model.

    gross edge = sum over legs of  sign * qty * multiplier *
                 (BS(model fair IV) - BS(market IV))
    i.e. how much more the position we would hold is worth under the model
    than under the market's own IV, per leg.  Legs the model has no opinion on
    keep their market IV and contribute zero.
    """
    if not fair_iv_by_strike:
        return ModelJudgement(
            model_id=model_id,
            available=False,
            verdict=VERDICT_UNAVAILABLE,
            reason="Model produced no fair IV for this structure.",
        )
    inconsistent = quote_consistency_problem(legs, market)
    if inconsistent is not None:
        return ModelJudgement(
            model_id=model_id,
            available=False,
            verdict=VERDICT_UNAVAILABLE,
            reason=f"Quotes inconsistent: {inconsistent}",
        )
    try:
        gross = 0.0
        for leg in legs:
            fair = float(fair_iv_by_strike.get(leg.strike, leg.market_iv))
            if not math.isfinite(fair) or fair <= 0.0:
                raise QuantInputError("model fair IV must be finite and positive")
            model_price = _bs(market, leg.strike, fair, leg.right)
            market_price = _bs(market, leg.strike, leg.market_iv, leg.right)
            gross += leg.sign * leg.quantity * leg.multiplier * (
                model_price - market_price
            )
    except (QuantInputError, ValueError, ZeroDivisionError) as exc:
        return ModelJudgement(
            model_id=model_id,
            available=False,
            verdict=VERDICT_UNAVAILABLE,
            reason=f"Could not re-price legs: {exc}",
        )

    if not math.isfinite(gross):
        return ModelJudgement(
            model_id=model_id,
            available=False,
            verdict=VERDICT_UNAVAILABLE,
            reason="Model edge was not a finite number.",
        )
    spread = sum(
        leg.quantity * leg.multiplier * abs(leg.entry_price - leg.mid)
        for leg in legs
    )
    fees = structure_fees_usd(legs)
    net = gross - spread - fees
    if net > 0.0:
        verdict = VERDICT_EDGE
    elif gross > 0.0:
        verdict = VERDICT_COSTS_EAT_EDGE
    else:
        verdict = VERDICT_AGAINST
    return ModelJudgement(
        model_id=model_id,
        available=True,
        verdict=verdict,
        fair_iv_by_strike=dict(fair_iv_by_strike),
        gross_edge_usd=gross,
        spread_cost_usd=spread,
        fees_usd=fees,
        net_edge_usd=net,
        net_edge_to_max_loss=(net / max_loss_usd) if max_loss_usd > 0 else None,
        detail=dict(detail or {}),
    )


def unavailable(model_id: str, reason: str) -> ModelJudgement:
    return ModelJudgement(
        model_id=model_id,
        available=False,
        verdict=VERDICT_UNAVAILABLE,
        reason=reason,
    )


def svi_fair_ivs(
    chain: Sequence[tuple[float, float]],
    market: MarketInputs,
    strikes: Sequence[float],
    *,
    exclude_strike: float | None = None,
) -> tuple[dict[float, float] | None, dict[str, Any], str | None]:
    """Fit a raw-SVI smile to (strike, iv) pairs of one expiry and read the
    fitted IV at ``strikes``.  Fails closed: no fit, no verdict.

    ``exclude_strike`` is left out of the fit (leave-one-out), so the model
    cannot simply reproduce the quote it is meant to be judging."""
    points = {}
    for strike, iv in chain:
        if exclude_strike is not None and abs(float(strike) - exclude_strike) < 1e-9:
            continue
        if math.isfinite(strike) and math.isfinite(iv) and iv > 0.0 and strike > 0.0:
            points[float(strike)] = float(iv)
    if len(points) < 5:
        return None, {"points": len(points)}, "Fewer than 5 usable strikes to fit a smile."
    forward = market.spot * math.exp(
        (market.rate - market.dividend_yield) * market.t_years
    )
    ks = [math.log(k / forward) for k in sorted(points)]
    ivs = [points[k] for k in sorted(points)]
    try:
        fit = svi_model.calibrate(ks, ivs, market.t_years)
    except (QuantInputError, ValueError) as exc:
        return None, {"points": len(points)}, f"SVI calibration failed: {exc}"
    # The optimiser's own ``converged`` flag is not used: it runs at a 1e-12
    # tolerance and reports failure when it merely runs out of iterations while
    # already reproducing the quotes.  What matters for pricing is (1) does the
    # fitted smile reproduce the quoted IVs and (2) is it free of butterfly
    # arbitrage, since we are pricing a butterfly.  (1) reuses the project's
    # existing IV-error classifier instead of a new threshold.
    fitted_ivs = []
    for k in ks:
        w = svi_model.total_variance(k, fit.parameters)
        fitted_ivs.append(math.sqrt(w / market.t_years) if w > 0 else float("nan"))
    errors = np.array(fitted_ivs) - np.array(ivs)
    iv_rmse = float(np.sqrt(np.mean(errors**2))) if np.all(np.isfinite(errors)) else float("inf")
    quality = classify_greek_quality(iv_rmse)
    # The library's own check samples out to +-150% log-moneyness, far beyond
    # any traded strike; a short-dated smile fitted on a +-10% window nearly
    # always "fails" out there.  A butterfly is priced inside the quoted range,
    # so arbitrage is tested over exactly that range (data and leg strikes).
    k_lo = min(min(ks), *(math.log(s_ / forward) for s_ in strikes))
    k_hi = max(max(ks), *(math.log(s_ / forward) for s_ in strikes))
    local = svi_model.sampled_static_arbitrage(
        fit.parameters, k_min=k_lo, k_max=max(k_hi, k_lo + 1e-6), points=201
    )
    arbitrage = bool(local["sampled_butterfly_arbitrage"])
    wing_arbitrage = bool(fit.static_arbitrage.get("sampled_butterfly_arbitrage"))
    diag = {
        "points": len(points),
        "iv_rmse": iv_rmse,
        "iv_fit_quality": quality.value,
        "sampled_butterfly_arbitrage": arbitrage,
        "wing_arbitrage_outside_quoted_range": wing_arbitrage,
        "optimiser_converged": bool(fit.diagnostics.converged),
        "optimiser_message": fit.diagnostics.message,
    }
    if svi_model.minimum_total_variance(fit.parameters) < 0.0:
        return None, diag, "Fitted SVI smile has negative total variance."
    if arbitrage:
        return None, diag, "Fitted SVI smile has sampled butterfly arbitrage; not used to price a butterfly."
    if quality is GreekQuality.BAD:
        return None, diag, f"SVI fit error too large (RMSE {iv_rmse * 100:.1f} vol points)."
    out: dict[float, float] = {}
    for strike in strikes:
        w = svi_model.total_variance(math.log(strike / forward), fit.parameters)
        if not math.isfinite(w) or w <= 0.0:
            return None, diag, "SVI returned a non-positive variance at a leg strike."
        out[float(strike)] = math.sqrt(w / market.t_years)
    return out, diag, None


def profit_profile(
    legs: Sequence[IdeaLeg],
    market: MarketInputs,
    *,
    atm_iv: float,
    fees_usd: float,
    grid_points: int = 6001,
) -> ProfitProfile:
    """Expiry payoff net of entry cash and fees, its profit zone, and a
    risk-neutral lognormal probability of landing in that zone."""
    if atm_iv <= 0.0 or market.t_years <= 0.0:
        raise QuantInputError("atm_iv and t_years must be positive")

    cash = entry_cashflow_usd(legs)

    def payoff(s: float) -> float:
        return cash + terminal_value_usd(legs, s) - fees_usd

    strikes = [leg.strike for leg in legs]
    # Piecewise linear: extremes occur at 0, a strike, or far above.
    probe = [0.0, *strikes, max(strikes) * 10.0]
    values = [payoff(s) for s in probe]
    max_profit, max_loss = max(values), -min(values)

    sigma_t = atm_iv * math.sqrt(market.t_years)
    drift = (market.rate - market.dividend_yield - 0.5 * atm_iv**2) * market.t_years
    lo = min(min(strikes), market.spot) * math.exp(-6.0 * sigma_t)
    hi = max(max(strikes), market.spot) * math.exp(6.0 * sigma_t)
    grid = np.exp(np.linspace(math.log(lo), math.log(hi), grid_points))
    pay = np.array([payoff(float(s)) for s in grid])

    def cdf(x: float) -> float:
        return float(norm.cdf((math.log(x / market.spot) - drift) / sigma_t))

    probs = np.array([cdf(float(s)) for s in grid])
    p = 0.0
    if pay[0] > 0.0:
        p += probs[0]
    if pay[-1] > 0.0:
        p += 1.0 - probs[-1]
    cell_mass = np.diff(probs)
    cell_pay = (pay[:-1] + pay[1:]) / 2.0
    p += float(cell_mass[cell_pay > 0.0].sum())

    breakevens: list[float] = []
    for i in range(len(grid) - 1):
        a, b = pay[i], pay[i + 1]
        if (a <= 0.0 < b) or (b <= 0.0 < a):
            frac = a / (a - b)
            breakevens.append(float(grid[i] + frac * (grid[i + 1] - grid[i])))

    intervals: list[tuple[float | None, float | None]] = []
    state = bool(pay[0] > 0.0)  # profitable at the far left edge?
    cur_start: float | None = None  # None = open on the left
    for be in breakevens:
        if state:
            intervals.append((cur_start, be))
            state = False
        else:
            cur_start = be
            state = True
    if state:
        intervals.append((cur_start, None))

    return ProfitProfile(
        max_profit_usd=float(max_profit),
        max_loss_usd=float(max_loss),
        breakevens=tuple(breakevens),
        profit_intervals=tuple(intervals),
        p_profit=float(min(max(p, 0.0), 1.0)),
        atm_iv=float(atm_iv),
        expected_move_1sd=float(market.spot * sigma_t),
    )


def payoff_curve(
    legs: Sequence[IdeaLeg],
    fees_usd: float,
    s_min: float,
    s_max: float,
    points: int = 241,
) -> list[tuple[float, float]]:
    """Expiry P&L (USD, after entry cash and fees) over a price range."""
    cash = entry_cashflow_usd(legs)
    step = (s_max - s_min) / (points - 1)
    return [
        (s_min + i * step, cash + terminal_value_usd(legs, s_min + i * step) - fees_usd)
        for i in range(points)
    ]


def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    if n <= 0:
        return None
    phat = successes / n
    denom = 1.0 + z * z / n
    centre = (phat + z * z / (2 * n)) / denom
    half = z * math.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


# --------------------------------------------------------------------------
# Database loading
# --------------------------------------------------------------------------
def _expiry_close_utc_years(captured_at: str, expiration: str) -> float | None:
    try:
        captured = datetime.fromisoformat(str(captured_at).replace("Z", "+00:00"))
    except ValueError:
        return None
    if captured.tzinfo is None:
        captured = captured.replace(tzinfo=NY)
    expiry_close = datetime.combine(
        date.fromisoformat(str(expiration)), dtime(16, 0), tzinfo=NY
    )
    seconds = (expiry_close - captured).total_seconds()
    if seconds <= 0:
        return None
    return seconds / (DAYS_PER_YEAR * 86400.0)


def _latest_provider_obs(conn, option_quote_id: int):
    return conn.execute(
        """
        SELECT implied_volatility, model_underlying_price, model_rate,
               model_dividend_yield
        FROM provider_model_observations
        WHERE option_quote_id = ? AND provider = 'THETADATA'
        ORDER BY id DESC LIMIT 1;
        """,
        (option_quote_id,),
    ).fetchone()


def _score_proposal_row(conn, row) -> TradeIdea:
    notes: list[str] = []
    proposal_id = int(row["proposal_id"])
    structure = json.loads(str(row["structure_json"]))
    pricing = json.loads(str(row["entry_pricing_json"]))
    price_by_quote = {
        int(item["option_quote_id"]): float(item["entry_price"])
        for item in pricing.get("legs", [])
    }

    legs: list[IdeaLeg] = []
    obs_rows = []
    snapshot_id = None
    for leg in structure.get("legs", []):
        quote_id = int(leg["option_quote_id"])
        quote = conn.execute(
            "SELECT snapshot_id, bid, ask FROM option_quotes WHERE id = ?;",
            (quote_id,),
        ).fetchone()
        obs = _latest_provider_obs(conn, quote_id)
        if quote is None or obs is None or obs["implied_volatility"] is None:
            raise ValueError(f"leg quote {quote_id} lacks a quote or provider IV")
        if quote["bid"] is None or quote["ask"] is None:
            raise ValueError(f"leg quote {quote_id} lacks bid/ask")
        leg_snapshot_id = int(quote["snapshot_id"])
        if snapshot_id is not None and leg_snapshot_id != snapshot_id:
            raise ValueError("structure legs come from different quote snapshots; cannot compare model edges")
        snapshot_id = leg_snapshot_id
        obs_rows.append(obs)
        legs.append(
            IdeaLeg(
                option_quote_id=quote_id,
                right=str(leg["right"]),
                strike=float(leg["strike"]),
                side=str(leg["side"]),
                quantity=int(leg["quantity"]),
                multiplier=float(leg["shares_per_contract"]),
                entry_price=price_by_quote[quote_id],
                bid=float(quote["bid"]),
                ask=float(quote["ask"]),
                market_iv=float(obs["implied_volatility"]),
            )
        )

    snap = conn.execute(
        "SELECT captured_at, underlying_price, us_session_date FROM market_snapshots WHERE id = ?;",
        (snapshot_id,),
    ).fetchone()
    spot = snap["underlying_price"]
    if spot is None:
        prices = [o["model_underlying_price"] for o in obs_rows if o["model_underlying_price"]]
        if prices:
            spot = float(sum(prices) / len(prices))
            notes.append("Spot taken from provider model input (no snapshot spot).")
    if spot is None or float(spot) <= 0.0:
        raise ValueError("no usable underlying price")
    spot = float(spot)

    t_years = _expiry_close_utc_years(snap["captured_at"], str(row["expiration"]))
    if t_years is None:
        raise ValueError("expiration is not after the snapshot time")

    rates = [o["model_rate"] for o in obs_rows if o["model_rate"] is not None]
    yields = [o["model_dividend_yield"] for o in obs_rows if o["model_dividend_yield"] is not None]
    stored = bool(rates) and bool(yields)
    rate = float(rates[0]) if rates else 0.0
    dividend = float(yields[0]) if yields else 0.0
    if not stored:
        notes.append(
            "Rate and/or dividend yield not stored; 0 assumed. This is second "
            "order for the edge (only IV differences are priced)."
        )
    market = MarketInputs(spot, t_years, rate, dividend, stored)

    target = float(row["target_strike"])
    right = str(row["right"])
    expiration = str(row["expiration"])

    # chain for SVI and ATM IV, same expiry and right, same snapshot
    chain_rows = conn.execute(
        """
        SELECT oq.strike AS strike, pmo.implied_volatility AS iv
        FROM option_quotes AS oq
        JOIN provider_model_observations AS pmo
          ON pmo.option_quote_id = oq.id AND pmo.provider = 'THETADATA'
        WHERE oq.snapshot_id = ? AND oq.expiration = ? AND oq.right = ?
          AND pmo.implied_volatility IS NOT NULL AND pmo.implied_volatility > 0
          AND pmo.id = (SELECT MAX(id) FROM provider_model_observations
                        WHERE option_quote_id = oq.id AND provider = 'THETADATA');
        """,
        (snapshot_id, expiration, right),
    ).fetchall()
    chain = [(float(r["strike"]), float(r["iv"])) for r in chain_rows]
    if chain:
        atm_iv = min(chain, key=lambda p: abs(p[0] - spot))[1]
    else:
        atm_iv = float(np.mean([leg.market_iv for leg in legs]))
        notes.append("ATM IV approximated from the legs (no chain found).")

    structure_max_loss_usd = float(row["max_theoretical_loss_minor"]) / 100.0
    fees = structure_fees_usd(legs)
    # The proposal's theoretical expiry maximum loss excludes commission.
    # Use the same round-trip fee allowance as the expiry payoff profile.
    max_loss_with_fees = structure_max_loss_usd + fees

    judgements: dict[str, ModelJudgement] = {}

    # V1: the scanner's linear-chord fair IV at the target strike.
    if row["v1_interpolated_iv"] is not None:
        judgements[MODEL_V1] = judge_model(
            MODEL_V1, legs, market, {target: float(row["v1_interpolated_iv"])},
            max_loss_usd=max_loss_with_fees,
            detail={"market_iv": row["v1_implied_volatility"], "wings": [row["v1_lower_strike"], row["v1_upper_strike"]]},
        )
    else:
        judgements[MODEL_V1] = unavailable(MODEL_V1, "No V1 scanner evaluation linked to this proposal.")

    # V2: quadratic leave-one-out fitted IV at the target quote.
    target_leg = next((l for l in legs if l.strike == target), None)
    v2 = None
    if target_leg is not None:
        v2 = conn.execute(
            """
            SELECT fitted_iv, loo_residual, observation_state, reason_code
            FROM local_surface_residual_v2_observations
            WHERE option_quote_id = ? ORDER BY id DESC LIMIT 1;
            """,
            (target_leg.option_quote_id,),
        ).fetchone()
    if v2 is not None and v2["fitted_iv"] is not None and float(v2["fitted_iv"]) > 0:
        judgements[MODEL_V2] = judge_model(
            MODEL_V2, legs, market, {target: float(v2["fitted_iv"])},
            max_loss_usd=max_loss_with_fees,
            detail={"loo_residual": v2["loo_residual"], "state": v2["observation_state"]},
        )
    else:
        reason = (
            "No V2 observation for the target quote."
            if v2 is None
            else f"V2 not usable: {v2['observation_state']} / {v2['reason_code']}"
        )
        judgements[MODEL_V2] = unavailable(MODEL_V2, reason)

    # SVI: smooth smile through the whole expiry.
    # Leave-one-out at the target and adjust only the target leg, exactly like
    # V1/V2, so the three columns answer the same question.
    fair, diag, why = svi_fair_ivs(chain, market, [target], exclude_strike=target)
    if fair is None:
        judgements[MODEL_SVI] = unavailable(MODEL_SVI, why or "SVI unavailable.")
    else:
        judgements[MODEL_SVI] = judge_model(
            MODEL_SVI, legs, market, fair,
            max_loss_usd=max_loss_with_fees, detail=diag,
        )

    try:
        profile = profit_profile(legs, market, atm_iv=atm_iv, fees_usd=fees)
    except (QuantInputError, ValueError) as exc:
        profile = None
        notes.append(f"Profit profile unavailable: {exc}")

    available = [j for j in judgements.values() if j.available]
    edges = [j.net_edge_usd for j in available if j.net_edge_usd is not None]
    ratios = [j.net_edge_to_max_loss for j in available if j.net_edge_to_max_loss is not None]
    session_date = snap["us_session_date"]
    dte = (date.fromisoformat(expiration) - date.fromisoformat(str(session_date))).days if session_date else None

    return TradeIdea(
        proposal_id=proposal_id,
        research_run_id=int(row["research_run_id"]),
        underlying=str(row["underlying"]),
        expiration=expiration,
        right=right,
        structure_id=row["structure_id"],
        anomaly_direction=str(row["anomaly_direction"]),
        target_strike=target,
        strikes=tuple(sorted({l.strike for l in legs})),
        dte=dte,
        session_date=str(session_date) if session_date else None,
        as_of=str(snap["captured_at"]),
        spot=spot,
        net_debit_usd=-entry_cashflow_usd(legs),
        max_loss_usd=max_loss_with_fees,
        fees_usd=fees,
        profile=profile,
        judgements=judgements,
        favouring=sum(1 for j in available if j.favours),
        available=len(available),
        median_net_edge_usd=median(edges) if edges else None,
        median_net_edge_to_max_loss=median(ratios) if ratios else None,
        admission_decision=row["admission_decision"],
        admission_reason=row["admission_reason"],
        candidate_id=int(row["candidate_id"]) if row["candidate_id"] is not None else None,
        notes=tuple(notes),
        legs=tuple(legs),
        market=market,
    )


_PROPOSAL_SELECT = """
    SELECT
        ssp.id AS proposal_id,
        ssp.research_run_id,
        ssp.underlying, ssp.expiration, ssp.right, ssp.target_strike,
        ssp.anomaly_direction, ssp.structure_id, ssp.structure_json,
        ssp.entry_pricing_json, ssp.max_theoretical_loss_minor,
        hse.interpolated_iv AS v1_interpolated_iv,
        hse.implied_volatility AS v1_implied_volatility,
        hse.lower_strike AS v1_lower_strike,
        hse.upper_strike AS v1_upper_strike,
        sad.decision AS admission_decision,
        sad.reason_code AS admission_reason,
        sad.candidate_id AS candidate_id
    FROM shadow_structure_proposals AS ssp
    LEFT JOIN hypothesis_scanner_evaluations AS hse
      ON hse.id = ssp.hypothesis_evaluation_id
    LEFT JOIN v_shadow_admission_decisions_all AS sad
      ON sad.proposal_id = ssp.id
     AND sad.decision_id = (
            SELECT MAX(d2.decision_id)
            FROM v_shadow_admission_decisions_all AS d2
            WHERE d2.proposal_id = ssp.id)
"""


def score_proposal(proposal_id: int, *, db_path=None) -> TradeIdea:
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            _PROPOSAL_SELECT
            + " WHERE ssp.id = ? AND ssp.proposal_state = 'PROPOSED';",
            (proposal_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"Proposal {proposal_id} is not a PROPOSED structure.")
        return _score_proposal_row(conn, row)
    finally:
        conn.close()


def load_current_ideas(
    *, db_path=None
) -> tuple[list[TradeIdea], list[tuple[int, str]], str | None]:
    """Score every proposal from the most recent research session, one per
    (underlying, expiration, right, target strike), newest first.

    Returns (ideas ranked best-first, [(proposal_id, error)], session_date).
    """
    conn = get_connection(db_path)
    try:
        latest = conn.execute(
            """
            SELECT MAX(rr.us_session_date) AS d
            FROM research_runs AS rr
            JOIN shadow_structure_proposals AS ssp ON ssp.research_run_id = rr.id
            WHERE ssp.proposal_state = 'PROPOSED';
            """
        ).fetchone()
        session_date = latest["d"] if latest else None
        if not session_date:
            return [], [], None
        rows = conn.execute(
            _PROPOSAL_SELECT
            + """
            JOIN research_runs AS rr ON rr.id = ssp.research_run_id
            WHERE ssp.proposal_state = 'PROPOSED'
              AND rr.us_session_date = ?
              AND ssp.expiration >= ?
              AND ssp.id = (
                    SELECT MAX(p2.id) FROM shadow_structure_proposals AS p2
                    JOIN research_runs AS r2 ON r2.id = p2.research_run_id
                    WHERE p2.underlying = ssp.underlying
                      AND p2.expiration = ssp.expiration
                      AND p2.right = ssp.right
                      AND p2.target_strike = ssp.target_strike
                      AND p2.proposal_state = 'PROPOSED'
                      AND r2.us_session_date = rr.us_session_date)
            ORDER BY ssp.id DESC;
            """,
            (session_date, session_date),
        ).fetchall()
        ideas: list[TradeIdea] = []
        errors: list[tuple[int, str]] = []
        for row in rows:
            try:
                ideas.append(_score_proposal_row(conn, row))
            except Exception as exc:  # one bad proposal must not hide the rest
                errors.append((int(row["proposal_id"]), f"{type(exc).__name__}: {exc}"))
        return rank_ideas(ideas), errors, str(session_date)
    finally:
        conn.close()


def rank_ideas(ideas: Sequence[TradeIdea]) -> list[TradeIdea]:
    """Most models agreeing first, then best median net edge relative to the
    money at risk.  Unscorable ideas sink to the bottom."""
    def key(idea: TradeIdea):
        ratio = idea.median_net_edge_to_max_loss
        return (
            -idea.favouring,
            -(ratio if ratio is not None else float("-inf")),
            idea.underlying,
        )

    return sorted(ideas, key=key)


# --------------------------------------------------------------------------
# Empirical track record per model (never from the models themselves)
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class ModelRecord:
    model_id: str
    n_scored: int  # resolved outcomes this model could judge
    n_favoured: int  # of those, where the model saw edge after costs
    wins: int  # favoured and net P&L > 0
    mean_net_pnl_usd: float | None
    hit_rate: float | None
    hit_rate_ci: tuple[float, float] | None
    mean_ci: tuple[float, float] | None


def model_track_record(*, db_path=None) -> tuple[dict[str, ModelRecord], int]:
    """Retrospective replay on historical entry inputs, not precommitted picks.

    Models are re-run now against stored proposal quotes, after expiry outcomes
    are already known. Returns (records, distinct resolved bets). This MUST NOT
    be described as a prospective or timestamped prediction track record.
    """
    conn = get_connection(db_path)
    try:
        has_table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='shadow_expiry_outcomes_v1';"
        ).fetchone()
        if not has_table:
            raise sqlite3.OperationalError(
                "Expiry-outcome evidence is unavailable until migration 035 is applied."
            )
        outcomes = conn.execute(
            """
            SELECT o.candidate_id, o.estimated_net_pnl_usd_minor AS net_minor,
                   sad.proposal_id
            FROM shadow_expiry_outcomes_v1 AS o
            JOIN v_shadow_admission_decisions_all AS sad
              ON sad.candidate_id = o.candidate_id AND sad.decision = 'ADMITTED'
            WHERE o.outcome_state = 'RESOLVED'
              -- outcomes are revisioned: only the current revision counts
              AND o.revision = (
                    SELECT MAX(r.revision) FROM shadow_expiry_outcomes_v1 AS r
                    WHERE r.candidate_id = o.candidate_id)
            ORDER BY o.id;
            """
        ).fetchall()
        pnls: dict[str, list[float]] = {m: [] for m in MODEL_ORDER}
        scored: dict[str, int] = {m: 0 for m in MODEL_ORDER}
        # The same anomaly can be admitted in several 15-minute slots.  Those
        # candidates share one expiry and therefore one terminal price: they
        # are one bet, not several independent ones.  Count each distinct
        # (underlying, expiry, right, target strike, structure) once, at its
        # earliest entry, so the sample size and intervals are not inflated.
        seen_bets: set[tuple] = set()
        distinct = 0
        for out in sorted(outcomes, key=lambda r: int(r["candidate_id"])):
            try:
                row = conn.execute(
                    _PROPOSAL_SELECT + " WHERE ssp.id = ?;", (int(out["proposal_id"]),)
                ).fetchone()
                idea = _score_proposal_row(conn, row)
            except Exception:
                continue
            bet = (idea.underlying, idea.expiration, idea.right,
                   idea.target_strike, idea.structure_id)
            if bet in seen_bets:
                continue
            seen_bets.add(bet)
            distinct += 1
            for model_id, judgement in idea.judgements.items():
                if not judgement.available:
                    continue
                scored[model_id] += 1
                if judgement.favours:
                    pnls[model_id].append(float(out["net_minor"]) / 100.0)
        records = {}
        for model_id in MODEL_ORDER:
            values = pnls[model_id]
            n = len(values)
            wins = sum(1 for v in values if v > 0)
            mean_ci = None
            if n >= 2:
                arr = np.array(values)
                se = float(arr.std(ddof=1) / math.sqrt(n))
                mean_ci = (float(arr.mean() - 1.96 * se), float(arr.mean() + 1.96 * se))
            records[model_id] = ModelRecord(
                model_id=model_id,
                n_scored=scored[model_id],
                n_favoured=n,
                wins=wins,
                mean_net_pnl_usd=(float(np.mean(values)) if n else None),
                hit_rate=(wins / n if n else None),
                hit_rate_ci=wilson_interval(wins, n),
                mean_ci=mean_ci,
            )
        return records, distinct
    finally:
        conn.close()


def _empty_record(model_id: str) -> ModelRecord:
    return ModelRecord(model_id, 0, 0, 0, None, None, None, None)
