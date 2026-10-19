"""Opportunity score, matched placebo, evidence engine and persistence."""
import json
import math
import sqlite3
from dataclasses import replace

import pytest

from src.database.repository import get_connection
from src.decision import opportunity as opp
from src.decision.opportunity import (
    Z_MARGINAL,
    Z_WORTH,
    ChainQuote,
    assess_idea,
    build_placebo_legs,
    leg_iv_sigma,
    rank_by_opportunity,
)
from src.decision.opportunity_evidence import (
    MIN_BETS,
    MIN_DATES,
    STATE_EVIDENCE,
    STATE_NO_DATA,
    STATE_NOT_BETTER,
    STATE_RELATIVE_NOT_PROFITABLE,
    STATE_TOO_EARLY,
    cluster_bootstrap_ci,
    evaluate,
)
from src.decision.trade_ideas import IdeaLeg, MarketInputs, load_current_ideas
from src.research.opportunity_pipeline import (
    assess_new_proposals,
    load_evidence_rows,
    resolve_opportunity_outcomes,
)
from tests.test_trade_ideas import EXPIRY, SESSION, seed_scenario

MARKET = MarketInputs(100.0, 30 / 365, 0.04, 0.0, True)


# ----------------------------------------------------------------- sigma ---
def test_leg_sigma_is_uniform_quote_width_over_vega():
    leg = IdeaLeg(1, "C", 100, "SELL", 2, 100, 2.35, 2.35, 2.55, 0.20)
    from src.quant.greeks import analytic
    from src.quant.types import VanillaOption

    vega = analytic(VanillaOption(100.0, 100.0, 30 / 365, 0.04, 0.20, "CALL")).vega
    assert leg_iv_sigma(leg, MARKET) == pytest.approx(0.20 / (math.sqrt(12) * vega))


def test_wider_quote_means_more_uncertainty():
    tight = IdeaLeg(1, "C", 100, "BUY", 1, 100, 2.45, 2.40, 2.45, 0.20)
    wide = IdeaLeg(1, "C", 100, "BUY", 1, 100, 2.60, 2.30, 2.60, 0.20)
    assert leg_iv_sigma(wide, MARKET) > leg_iv_sigma(tight, MARKET)


def test_zero_vega_is_infinite_uncertainty_not_a_crash():
    deep = IdeaLeg(1, "C", 400, "BUY", 1, 100, 0.05, 0.0, 0.05, 0.20)
    assert leg_iv_sigma(deep, MARKET) == math.inf


# -------------------------------------------------------------- assessing ---
def _idea(db_path, **kw):
    seed_scenario(db_path, with_v2=True)
    ideas, errors, _ = load_current_ideas(db_path=db_path)
    assert not errors
    return ideas[0]


def test_assessment_is_deterministic_and_complete(db_path):
    idea = _idea(db_path)
    a, b = assess_idea(idea), assess_idea(idea)
    assert a == b
    assert a.verdict in (opp.VERDICT_WORTH, opp.VERDICT_MARGINAL, opp.VERDICT_SKIP)
    assert a.score is not None and a.net_edge_usd is not None
    assert a.models_available == 3
    assert a.headline and a.reason_code
    for key in ("dte", "fair_ivs", "max_spread_to_mid", "fees_usd", "sigma_target_vol_pts"):
        assert key in a.features
    assert a.features["quote_uncertainty_basis"] == "BID_ASK_WIDTH_UNIFORM_ONLY"
    assert a.features["latent_midpoint_noise_measured"] is False
    assert a.features["model_fit_independence_assumed"] is False
    assert a.features["prospective_profitability_proven"] is False


def test_score_is_net_over_noise_scaled_edge(db_path):
    idea = _idea(db_path)
    a = assess_idea(idea)
    sigma_total = math.hypot(a.sigma_quote_vol_pts, a.sigma_model_vol_pts) / 100.0
    usd_per_iv = abs(a.gross_edge_usd) / (abs(a.residual_vol_pts) / 100.0)
    assert a.score == pytest.approx(a.net_edge_usd / (usd_per_iv * sigma_total))


def test_costs_are_charged_in_full(db_path):
    idea = _idea(db_path)
    base = assess_idea(idea)
    # Quote the wings wider: spread cost rises, net edge must fall, score must fall.
    wider = tuple(
        replace(l, entry_price=l.entry_price + (0.30 if l.side == "BUY" else -0.30),
                ask=l.ask + 0.30, bid=max(l.bid - 0.30, 0.01))
        for l in idea.legs
    )
    worse = assess_idea(replace(idea, legs=wider))
    if worse.net_edge_usd is not None:
        assert worse.net_edge_usd < base.net_edge_usd
        assert worse.score < base.score


def test_verdict_thresholds_are_applied_in_order(db_path, monkeypatch):
    idea = _idea(db_path)
    sigma = {leg.option_quote_id: 0.0001 for leg in idea.legs}
    samples = {leg.option_quote_id: 8 for leg in idea.legs}

    def calibrated():
        return assess_idea(
            idea,
            historical_iv_sigma_by_quote_id=sigma,
            historical_iv_samples_by_quote_id=samples,
        )

    a = calibrated()
    for z_worth, z_marg, expected in (
        (a.score - 0.5, a.score - 1.0, opp.VERDICT_WORTH),
        (a.score + 0.5, a.score - 0.5, opp.VERDICT_MARGINAL),
        (a.score + 1.0, a.score + 0.5, opp.VERDICT_SKIP),
    ):
        monkeypatch.setattr(opp, "Z_WORTH", z_worth)
        monkeypatch.setattr(opp, "Z_MARGINAL", z_marg)
        assert calibrated().verdict == expected


def test_too_few_models_is_skip_not_zero(db_path):
    seed_scenario(db_path, with_v2=False, omit_iv_strike=None)
    ideas, _, _ = load_current_ideas(db_path=db_path)
    idea = ideas[0]
    only_one = {k: v for k, v in list(idea.judgements.items())[:1]}
    stripped = replace(idea, judgements=only_one)
    a = assess_idea(stripped)
    assert a.verdict == opp.VERDICT_SKIP and a.reason_code == "TOO_FEW_MODELS"
    assert a.score is None


def test_skip_when_gross_edge_is_negative(db_path):
    idea = _idea(db_path)
    flipped = replace(
        idea,
        legs=tuple(replace(l, side="SELL" if l.side == "BUY" else "BUY") for l in idea.legs),
    )
    a = assess_idea(flipped)
    assert a.verdict == opp.VERDICT_SKIP and a.reason_code in ("NO_EDGE", "COSTS_EAT_EDGE")


def test_ranking_puts_worth_a_look_first_then_score(db_path):
    idea = _idea(db_path)
    pairs = rank_by_opportunity([idea, replace(idea, underlying="ZZZ")])
    ranks = [opp.VERDICT_RANK[a.verdict] for _, a in pairs]
    assert ranks == sorted(ranks)


# ---------------------------------------------------------------- placebo ---
def _chain(centres=range(90, 111), spread=0.10):
    out = []
    for i, k in enumerate(centres):
        mid = max(0.5, 10.0 - 0.45 * (k - 90))
        out.append(ChainQuote(100 + i, float(k), mid - spread / 2, mid + spread / 2, 0.2, 100.0))
    return out


def _fly(direction="BUY"):
    other = "SELL" if direction == "BUY" else "BUY"
    legs = (
        IdeaLeg(1, "C", 95, direction, 1, 100, 5.92, 5.72, 5.92, 0.20),
        IdeaLeg(2, "C", 100, other, 2, 100, 2.35, 2.35, 2.55, 0.20),
        IdeaLeg(3, "C", 105, direction, 1, 100, 0.81, 0.61, 0.81, 0.20),
    )
    return legs


def test_placebo_keeps_shape_direction_and_never_picks_the_signal_centre(db_path):
    idea = replace(_idea(db_path), legs=_fly("BUY"), market=MARKET)
    seen = set()
    for seed in range(60):
        legs = build_placebo_legs(idea, _chain(), seed=seed)
        assert legs is not None
        lo, mid, hi = sorted(legs, key=lambda l: l.strike)
        assert mid.strike != idea.target_strike
        assert mid.strike - lo.strike == pytest.approx(5.0) and hi.strike - mid.strike == pytest.approx(5.0)
        assert [l.quantity for l in (lo, mid, hi)] == [1, 2, 1]
        assert [l.side for l in (lo, mid, hi)] == ["BUY", "SELL", "BUY"]
        for l in legs:  # same conservative pricing as a real proposal
            assert l.entry_price == (l.ask if l.side == "BUY" else l.bid)
        seen.add(mid.strike)
    assert len(seen) > 3  # genuinely random across the eligible centres


def test_placebo_is_reproducible_for_a_seed(db_path):
    idea = replace(_idea(db_path), legs=_fly("BUY"), market=MARKET)
    a = build_placebo_legs(idea, _chain(), seed=7)
    b = build_placebo_legs(idea, _chain(), seed=7)
    assert a == b


def test_placebo_skips_illiquid_strikes_and_may_not_exist(db_path):
    idea = replace(_idea(db_path), legs=_fly("BUY"), market=MARKET)
    assert build_placebo_legs(idea, _chain(spread=6.0), seed=1) is None  # all too wide
    assert build_placebo_legs(idea, _chain(centres=[95, 100, 105]), seed=1) is None  # only the signal


# --------------------------------------------------------------- evidence ---
def _rows(n_bets, n_dates, signal_edge, placebo_edge=-24.0, noise=15.0, verdict=opp.VERDICT_WORTH, seed=1):
    import random

    rng = random.Random(seed)
    rows = []
    for i in range(n_bets):
        rows.append({
            "proposal_id": i + 1,
            "bet_key": ("X", f"2026-10-{(i % n_dates) + 1:02d}", "C", float(100 + i), "S"),
            "expiration": f"2026-10-{(i % n_dates) + 1:02d}",
            "verdict": verdict,
            "score": 2.5 + rng.random(),
            "signal_net": signal_edge + rng.gauss(0, noise),
            "placebo_net": placebo_edge + rng.gauss(0, noise),
        })
    return rows


def test_no_data_and_too_early_states():
    assert evaluate([]).state == STATE_NO_DATA
    assert evaluate(_rows(5, 5, 50)).state == STATE_TOO_EARLY
    assert evaluate(_rows(MIN_BETS, MIN_DATES - 1, 50)).state == STATE_TOO_EARLY


def test_real_edge_is_detected_and_null_is_not():
    real = evaluate(_rows(120, 15, signal_edge=30.0))
    assert real.state == STATE_EVIDENCE and real.primary_ci_usd[0] > 0
    null = evaluate(_rows(120, 15, signal_edge=-24.0))
    assert null.state == STATE_NOT_BETTER and null.primary_ci_usd[0] <= 0 <= null.primary_ci_usd[1]


def test_relative_placebo_outperformance_is_not_mistaken_for_profit():
    # A clearly stronger strike choice is still economically unprofitable
    # when the selected positions lose net money after assumed costs.
    losing = evaluate(_rows(120, 15, signal_edge=-30.0, placebo_edge=-100.0, noise=1.0))
    assert losing.primary_ci_usd is not None and losing.primary_ci_usd[0] > 0
    assert losing.primary_signal_mean_net_usd < 0
    assert losing.primary_placebo_mean_net_usd < 0
    assert losing.state == STATE_RELATIVE_NOT_PROFITABLE
    assert "not evidence of a profitable strategy" in losing.headline

    # Even an absolute-profit sample is inconclusive under the deliberately
    # stronger operating rule when a random-strike control also earns money.
    both_win = evaluate(_rows(120, 15, signal_edge=50.0, placebo_edge=10.0, noise=1.0))
    assert both_win.primary_ci_usd[0] > 0
    assert both_win.primary_signal_mean_net_usd > 0
    assert both_win.primary_placebo_mean_net_usd > 0
    assert both_win.state == STATE_RELATIVE_NOT_PROFITABLE


def test_false_positive_rate_of_the_test_is_controlled():
    hits = sum(
        evaluate(_rows(60, 12, signal_edge=-24.0, seed=s)).state == STATE_EVIDENCE for s in range(60)
    )
    assert hits <= 6  # nominal 2.5% one-sided; generous bound for 60 trials


def test_same_bet_in_many_slots_counts_once():
    base = _rows(40, 10, 30.0)
    dup = base + [dict(r, proposal_id=r["proposal_id"] + 1000) for r in base]
    assert evaluate(dup).primary_bets == evaluate(base).primary_bets == 40


def test_cluster_bootstrap_is_wider_when_bets_share_a_market_move():
    # Ten bets per expiry date, all moving with that date's market (shared shock).
    shocks = [12.0, -9.0, 15.0, -14.0]
    vals, same_date, own_date = [], [], []
    for d, shock in enumerate(shocks):
        for j in range(10):
            vals.append(shock + 0.1 * j)
            same_date.append(f"d{d}")
            own_date.append(f"d{d}_{j}")
    clustered = cluster_bootstrap_ci(vals, same_date)
    naive = cluster_bootstrap_ci(vals, own_date)
    assert (clustered[1] - clustered[0]) > 2 * (naive[1] - naive[0])


def test_missing_placebos_are_reported_not_hidden():
    rows = _rows(40, 10, 30.0)
    rows[0]["placebo_net"] = None
    rep = evaluate(rows)
    assert rep.bets_without_placebo == 1


def test_secondary_buckets_never_drive_the_state():
    rows = _rows(80, 12, 50.0, verdict=opp.VERDICT_MARGINAL)
    rep = evaluate(rows)
    assert rep.state == STATE_TOO_EARLY  # no WORTH bets, so no claim
    assert any(b.verdict == opp.VERDICT_MARGINAL and b.bets == 80 for b in rep.buckets)


# ---------------------------------------------------------- persistence ---
def _seed_with_chain(db_path):
    """seed_scenario has one PROPOSED structure and a full 9-strike chain."""
    return seed_scenario(db_path, with_v2=True)


def test_assess_writes_signal_and_placebo_once(db_path):
    ids = _seed_with_chain(db_path)
    res = assess_new_proposals(research_run_id=ids["run_id"], db_path=db_path)
    assert res.assessed == 1 and res.errors == 0
    again = assess_new_proposals(research_run_id=ids["run_id"], db_path=db_path)
    assert again.assessed == 0  # idempotent
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT kind, verdict, score, features_json, legs_json FROM opportunity_assessments_v1 "
            "ORDER BY kind;").fetchall()
    finally:
        conn.close()
    kinds = [r["kind"] for r in rows]
    assert kinds.count("SIGNAL") == 1
    signal = next(r for r in rows if r["kind"] == "SIGNAL")
    feats = json.loads(signal["features_json"])
    assert "db" in feats and feats["db"]["chain_strikes"] == 9
    research = feats["strategy_comparison_v1"]
    assert research["state"] == "RESEARCH_ONLY_NO_VALIDATED_STRATEGY_EDGE"
    assert research["source_snapshot_id"] == ids["snapshot_id"]
    assert len(research["variants"]) == 7
    assert {r["strategy_id"] for r in research["variants"]} == {
        "S03", "S04", "S06", "S07", "S08", "S09", "S10"
    }
    assert all(r["comparison_state"] != "RECOMMENDED" for r in research["variants"])
    assert len(json.loads(signal["legs_json"])) == 3
    if "PLACEBO" in kinds:  # needs a second eligible centre in the 9-strike chain
        p = next(r for r in rows if r["kind"] == "PLACEBO")
        assert p["verdict"] == "PLACEBO" and p["score"] is None


def test_assessments_and_outcomes_are_append_only(db_path):
    ids = _seed_with_chain(db_path)
    assess_new_proposals(research_run_id=ids["run_id"], db_path=db_path)
    conn = get_connection(db_path)
    try:
        for stmt in (
            "UPDATE opportunity_assessments_v1 SET verdict='WORTH A LOOK';",
            "DELETE FROM opportunity_assessments_v1;",
        ):
            with pytest.raises(sqlite3.DatabaseError, match="append-only"):
                conn.execute(stmt)
    finally:
        conn.close()


def _expiry_snapshot(db_path, price, underlying="AAPL", *, verified_source=True):
    conn = get_connection(db_path)
    try:
        rid = int(conn.execute(
            """INSERT INTO research_runs (cohort_id, preregistration_hash, code_git_sha, started_at,
                ended_at, us_session_date, us_session_state, status)
               VALUES ('T','h','s','2026-09-18T19:00:00Z','2026-09-18T19:01:00Z',?, 'INTRADAY','COMPLETED');""",
            (EXPIRY,)).lastrowid)
        conn.execute(
            """INSERT INTO market_snapshots (captured_at, underlying, provider, research_run_id,
                us_session_date, us_session_state, underlying_source, fx_source,
                underlying_price, underlying_at, notes)
               VALUES ('2026-09-18T19:55:00Z', ?, 'THETADATA', ?, ?, 'INTRADAY',
                       'FETCHED','UNKNOWN', ?, '2026-09-18T19:55:00Z',
                        ?);""",
            (underlying, rid, EXPIRY, price,
             ('stock price source=MASSIVE_OPTION_CHAIN_UNDERLYING_ASSET_LAST; test fixture only.'
              if verified_source else None)))
        later = int(conn.execute(
            """INSERT INTO research_runs (cohort_id, preregistration_hash, code_git_sha, started_at,
                ended_at, us_session_date, us_session_state, status)
               VALUES ('T','h','s','2026-09-21T14:00:00Z','2026-09-21T14:01:00Z','2026-09-21','INTRADAY','COMPLETED');"""
        ).lastrowid)
        conn.commit()
        return later
    finally:
        conn.close()


def test_resolution_uses_terminal_price_and_pays_fees(db_path):
    ids = _seed_with_chain(db_path)
    assess_new_proposals(research_run_id=ids["run_id"], db_path=db_path)
    later = _expiry_snapshot(db_path, price=100.0)  # ends exactly at the body: max profit
    res = resolve_opportunity_outcomes(research_run_id=later, db_path=db_path)
    assert res.resolved >= 1 and res.awaiting_terminal_price == 0
    again = resolve_opportunity_outcomes(research_run_id=later, db_path=db_path)
    assert again.due == 0  # never resolved twice
    rows = load_evidence_rows(db_path=db_path)
    assert len(rows) == 1
    # long 95/100/105 fly closing at 100 is worth $500 at expiry
    conn = get_connection(db_path)
    try:
        o = conn.execute(
            "SELECT o.* FROM opportunity_outcomes_v1 o JOIN opportunity_assessments_v1 a "
            "ON a.id=o.assessment_id WHERE a.kind='SIGNAL';").fetchone()
        a = conn.execute("SELECT * FROM opportunity_assessments_v1 WHERE kind='SIGNAL';").fetchone()
    finally:
        conn.close()
    assert o["terminal_value_usd"] == pytest.approx(500.0)
    assert o["net_pnl_usd"] == pytest.approx(500.0 + a["entry_cashflow_usd"] - a["fees_usd"])


def test_not_resolved_before_the_expiry_session_has_passed(db_path):
    ids = _seed_with_chain(db_path)
    assess_new_proposals(research_run_id=ids["run_id"], db_path=db_path)
    res = resolve_opportunity_outcomes(research_run_id=ids["run_id"], db_path=db_path)
    assert res.due == 0


def test_expiry_without_a_stored_price_waits_instead_of_inventing_one(db_path):
    ids = _seed_with_chain(db_path)
    assess_new_proposals(research_run_id=ids["run_id"], db_path=db_path)
    conn = get_connection(db_path)
    try:
        later = int(conn.execute(
            """INSERT INTO research_runs (cohort_id, preregistration_hash, code_git_sha, started_at,
                ended_at, us_session_date, us_session_state, status)
               VALUES ('T','h','s','2026-09-21T14:00:00Z','2026-09-21T14:01:00Z','2026-09-21','INTRADAY','COMPLETED');"""
        ).lastrowid)
        conn.commit()
    finally:
        conn.close()
    res = resolve_opportunity_outcomes(research_run_id=later, db_path=db_path)
    assert res.resolved == 0 and res.awaiting_terminal_price == res.due >= 1


def test_evidence_loader_fails_soft_signal_before_migration(tmp_path):
    empty = tmp_path / "old.db"
    sqlite3.connect(empty).close()
    with pytest.raises(sqlite3.OperationalError):
        load_evidence_rows(db_path=empty)


def test_unverified_terminal_price_cannot_supply_profitability_evidence(db_path):
    ids = _seed_with_chain(db_path)
    assess_new_proposals(research_run_id=ids["run_id"], db_path=db_path)
    later = _expiry_snapshot(db_path, price=100.0, verified_source=False)
    result = resolve_opportunity_outcomes(research_run_id=later, db_path=db_path)
    assert result.resolved == 0
    assert result.awaiting_terminal_price >= 1
    assert load_evidence_rows(db_path=db_path) == []


def test_unverified_quote_multipliers_never_create_a_random_strike_placebo():
    from src.research.opportunity_pipeline import _verified_placebo_chain
    source = {
        "id": 1, "strike": 100, "bid": 4.5, "ask": 4.7, "iv": .3,
        "shares_per_contract": None, "reference_multiplier": None,
    }
    assert _verified_placebo_chain([source]) == []
    trusted = _verified_placebo_chain([
        {**source, "reference_multiplier": 100},
        {**source, "id": 2, "shares_per_contract": 10, "reference_multiplier": 100},
        {**source, "id": 3, "shares_per_contract": 100, "reference_multiplier": None},
    ])
    assert [x.option_quote_id for x in trusted] == [1, 3]
    assert all(x.multiplier == 100 for x in trusted)
