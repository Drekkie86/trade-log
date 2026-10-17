"""Trade ideas: per-model judgements, profit profile, ranking, track record."""
import json
import math

import pytest

from src.database.repository import get_connection
from src.decision.trade_ideas import (
    MODEL_ORDER,
    MODEL_V1,
    MODEL_V2,
    VERDICT_AGAINST,
    VERDICT_COSTS_EAT_EDGE,
    VERDICT_EDGE,
    VERDICT_UNAVAILABLE,
    IdeaLeg,
    MarketInputs,
    entry_cashflow_usd,
    judge_model,
    load_current_ideas,
    model_track_record,
    profit_profile,
    score_proposal,
    structure_fees_usd,
    svi_fair_ivs,
    wilson_interval,
)
from src.quant.black_scholes import price as bs_price
from src.quant.types import VanillaOption

# --------------------------------------------------------------------------
# Pure: a textbook 95/100/105 long call butterfly
# --------------------------------------------------------------------------
MARKET = MarketInputs(100.0, 30 / 365, 0.04, 0.0, True)


def fly_legs():
    return [
        IdeaLeg(1, "C", 95, "BUY", 1, 100, 6.20, 6.00, 6.20, 0.20),
        IdeaLeg(2, "C", 100, "SELL", 2, 100, 2.90, 2.90, 3.10, 0.20),
        IdeaLeg(3, "C", 105, "BUY", 1, 100, 1.05, 0.95, 1.05, 0.20),
    ]


def test_entry_cash_fees_and_payoff_numbers():
    legs = fly_legs()
    # pay 620 + 105, receive 580 -> debit 145
    assert entry_cashflow_usd(legs) == pytest.approx(-145.0)
    # 4 contract sides * 2 * $3.00
    assert structure_fees_usd(legs) == pytest.approx(24.0)
    prof = profit_profile(legs, MARKET, atm_iv=0.20, fees_usd=24.0)
    assert prof.max_loss_usd == pytest.approx(169.0)  # debit + fees
    assert prof.max_profit_usd == pytest.approx(331.0)  # 5*100 - debit - fees
    lo, hi = prof.breakevens
    assert lo == pytest.approx(95 + 1.69, abs=0.02)
    assert hi == pytest.approx(105 - 1.69, abs=0.02)
    assert prof.profit_intervals == ((pytest.approx(lo), pytest.approx(hi)),)
    # probability mass of the profit zone under the stated lognormal
    sig = 0.20 * math.sqrt(30 / 365)
    drift = (0.04 - 0.5 * 0.2**2) * 30 / 365
    from scipy.stats import norm

    exact = norm.cdf((math.log(hi / 100) - drift) / sig) - norm.cdf(
        (math.log(lo / 100) - drift) / sig
    )
    assert prof.p_profit == pytest.approx(exact, abs=2e-3)
    assert prof.expected_move_1sd == pytest.approx(100 * sig)


def test_reverse_butterfly_profits_in_the_tails():
    legs = [
        IdeaLeg(1, "C", 95, "SELL", 1, 100, 6.00, 6.00, 6.20, 0.20),
        IdeaLeg(2, "C", 100, "BUY", 2, 100, 3.10, 2.90, 3.10, 0.20),
        IdeaLeg(3, "C", 105, "SELL", 1, 100, 0.95, 0.95, 1.05, 0.20),
    ]
    prof = profit_profile(legs, MARKET, atm_iv=0.20, fees_usd=structure_fees_usd(legs))
    assert len(prof.profit_intervals) == 2
    assert prof.profit_intervals[0][0] is None  # open on the left
    assert prof.profit_intervals[1][1] is None  # open on the right
    assert 0.0 < prof.p_profit < 1.0


def test_model_below_market_iv_favours_selling_the_middle():
    legs = fly_legs()
    prof = profit_profile(legs, MARKET, atm_iv=0.20, fees_usd=24.0)
    j = judge_model(MODEL_V1, legs, MARKET, {100.0: 0.17}, max_loss_usd=prof.max_loss_usd)
    assert j.available and j.verdict == VERDICT_EDGE and j.favours
    # net = gross - spread - fees, exactly
    assert j.net_edge_usd == pytest.approx(j.gross_edge_usd - j.spread_cost_usd - j.fees_usd)
    # crossing half-spreads: 0.10*100 + 0.10*200 + 0.05*100 = $35
    assert j.spread_cost_usd == pytest.approx(35.0)
    assert j.fees_usd == pytest.approx(24.0)
    assert j.net_edge_to_max_loss == pytest.approx(j.net_edge_usd / 169.0)


def test_costs_are_charged_and_can_eat_the_edge():
    legs = fly_legs()
    tiny = judge_model(MODEL_V1, legs, MARKET, {100.0: 0.199}, max_loss_usd=169.0)
    assert tiny.gross_edge_usd > 0 and tiny.net_edge_usd < 0
    assert tiny.verdict == VERDICT_COSTS_EAT_EDGE and not tiny.favours


def test_model_above_market_iv_disagrees():
    j = judge_model(MODEL_V1, fly_legs(), MARKET, {100.0: 0.24}, max_loss_usd=169.0)
    assert j.verdict == VERDICT_AGAINST and not j.favours


def test_only_priced_difference_matters_so_rate_basis_cancels():
    legs = fly_legs()
    a = judge_model(MODEL_V1, legs, MARKET, {100.0: 0.17}, max_loss_usd=169.0)
    shifted = MarketInputs(100.0, 30 / 365, 0.0, 0.0, False)
    b = judge_model(MODEL_V1, legs, shifted, {100.0: 0.17}, max_loss_usd=169.0)
    assert abs(a.gross_edge_usd - b.gross_edge_usd) < 0.05 * abs(a.gross_edge_usd)


def test_no_fair_iv_means_unavailable_not_zero():
    j = judge_model(MODEL_V2, fly_legs(), MARKET, {}, max_loss_usd=169.0)
    assert j.verdict == VERDICT_UNAVAILABLE and not j.available and not j.favours
    assert j.net_edge_usd is None


def test_svi_fails_closed_on_too_few_strikes():
    fair, _, why = svi_fair_ivs([(95, 0.2), (100, 0.2), (105, 0.2)], MARKET, [100.0])
    assert fair is None and "Fewer than 5" in why


def test_svi_is_used_when_it_reproduces_quotes_even_if_optimiser_hits_its_iteration_cap():
    # Regression: a gentle smile with a 1.2-vol-point bump used to be rejected
    # because the optimiser ran out of iterations at a 1e-12 tolerance.
    strikes = [90, 92.5, 95, 97.5, 100, 102.5, 105, 107.5, 110]
    chain = [(k, 0.20 + 0.00012 * (k - 100) ** 2 + (0.012 if k == 100 else 0.0)) for k in strikes]
    market = MarketInputs(100.0, 17 / 365, 0.04, 0.0, True)
    fair, diag, why = svi_fair_ivs(chain, market, [100.0])
    assert why is None and fair is not None
    assert diag["iv_fit_quality"] != "BAD" and diag["iv_rmse"] < 0.005
    assert fair[100.0] < chain[4][1]  # smooth smile sits below the bumped strike


def test_svi_rejects_a_fit_that_does_not_reproduce_the_chain():
    import random

    rng = random.Random(7)
    strikes = [90, 92.5, 95, 97.5, 100, 102.5, 105, 107.5, 110]
    chain = [(k, 0.20 + rng.uniform(-0.12, 0.12)) for k in strikes]
    market = MarketInputs(100.0, 17 / 365, 0.04, 0.0, True)
    fair, diag, why = svi_fair_ivs(chain, market, [100.0])
    assert fair is None and why is not None
    assert "too large" in why or "arbitrage" in why or "negative" in why


def test_wilson_interval_known_values():
    assert wilson_interval(0, 0) is None
    lo, hi = wilson_interval(5, 10)
    assert lo == pytest.approx(0.2366, abs=1e-3) and hi == pytest.approx(0.7634, abs=1e-3)


# --------------------------------------------------------------------------
# Database scenario: a full 9-strike chain with a rich 100 strike
# --------------------------------------------------------------------------
STRIKES = [90, 92.5, 95, 97.5, 100, 102.5, 105, 107.5, 110]
SESSION = "2026-09-01"
CAPTURED = "2026-09-01T18:00:05Z"  # 14:00 New York
EXPIRY = "2026-09-18"
T = 17.0 / 365  # approx; only used to build prices
RICH = 0.04


def smile(k):
    return 0.20 + 0.00012 * (k - 100) ** 2 + (RICH if k == 100 else 0.0)


def px(k, iv):
    return bs_price(
        VanillaOption(spot=100.0, strike=float(k), time_to_expiry=T, rate=0.04,
                      volatility=iv, right="CALL")
    )


def seed_scenario(db_path, *, with_v2=False, underlying="AAPL", omit_iv_strike=None):
    conn = get_connection(db_path)
    try:
        run_id = int(conn.execute(
            """INSERT INTO research_runs (cohort_id, preregistration_hash, code_git_sha,
                started_at, ended_at, us_session_date, us_session_state, status)
               VALUES ('T','h','s','2026-09-01T18:00:00Z','2026-09-01T18:01:00Z',?,'INTRADAY','COMPLETED');""",
            (SESSION,)).lastrowid)
        ref_id = int(conn.execute(
            """INSERT INTO listing_reference_contracts (research_run_id, provider, underlying,
                provider_contract_id, expiration, strike, right, shares_per_contract,
                observed_at, ingested_at)
               VALUES (?, 'MASSIVE', ?, ?, ?, 100, 'C', 100, '2026-09-01T18:00:00Z', '2026-09-01T18:00:00Z');""",
            (run_id, underlying, f"O:{underlying}T", EXPIRY)).lastrowid)
        for provider, family in (("MASSIVE", "MASSIVE_SNAPSHOT"), ("THETADATA", "THETADATA_QUOTE"),
                                 ("THETADATA", "THETADATA_GREEKS")):
            conn.execute(
                """INSERT INTO provider_observation_availability (reference_contract_id, provider,
                    evidence_family, state, observed_at, ingested_at)
                   VALUES (?, ?, ?, 'PRESENT', '2026-09-01T18:00:05Z', '2026-09-01T18:00:05Z');""",
                (ref_id, provider, family))
        snap_id = int(conn.execute(
            """INSERT INTO market_snapshots (captured_at, underlying, provider, research_run_id,
                us_session_date, us_session_state, underlying_source, fx_source, underlying_price)
               VALUES (?, ?, 'THETADATA', ?, ?, 'INTRADAY', 'FETCHED', 'UNKNOWN', 100.0);""",
            (CAPTURED, underlying, run_id, SESSION)).lastrowid)
        qid = {}
        for k in STRIKES:
            iv = smile(k)
            mid = px(k, iv)
            qid[k] = int(conn.execute(
                """INSERT INTO option_quotes (snapshot_id, provider_contract_id, right, strike,
                    expiration, quote_at, bid, bid_source, bid_at, ask, ask_source, ask_at,
                    last_source, iv_source, delta_source, gamma_source, theta_source, vega_source,
                    volume_source, open_interest_source)
                   VALUES (?, ?, 'C', ?, ?, '2026-09-01T14:00:00', ?, 'FETCHED', '2026-09-01T14:00:00',
                    ?, 'FETCHED', '2026-09-01T14:00:00', 'UNKNOWN','UNKNOWN','UNKNOWN','UNKNOWN',
                    'UNKNOWN','UNKNOWN','UNKNOWN','UNKNOWN');""",
                (snap_id, f"TH:{underlying}:{k}", k, EXPIRY, round(max(mid - 0.05, 0.0), 4),
                 round(mid + 0.05, 4))).lastrowid)
            if omit_iv_strike == k:
                continue
            conn.execute(
                """INSERT INTO provider_model_observations (option_quote_id, provider, ingested_at,
                    observed_at, model_name, implied_volatility, delta, model_underlying_price,
                    model_rate, model_dividend_yield, model_input_notes)
                   VALUES (?, 'THETADATA', ?, '2026-09-01T14:00:00', 'first_order', ?, 0.5, 100.0,
                    0.04, 0.0, '{}');""",
                (qid[k], CAPTURED, iv))
        scanner_run = int(conn.execute(
            """INSERT INTO hypothesis_scanner_runs (research_run_id, scanner_family_id, scanner_version,
                rule_version, hypothesis_family, hypothesis_version, config_hash, config_json,
                evaluated_at, structural_input_count, evaluable_count, surfaced_count)
               VALUES (?, 'LOCAL_IV_RESIDUAL_V1','1.0.0','LOCAL_IV_RESIDUAL_RULES_V1',
                'LOCAL_SURFACE_IV_RESIDUAL','1.0.0',?, '{}','2026-09-01T18:00:06Z',1,1,1);""",
            (run_id, "a" * 64)).lastrowid)
        chord = (smile(95) + smile(105)) / 2
        eval_id = int(conn.execute(
            """INSERT INTO hypothesis_scanner_evaluations (scanner_run_id, reference_contract_id,
                option_quote_id, underlying, expiration, strike, right, delta, implied_volatility,
                lower_strike, lower_iv, upper_strike, upper_iv, interpolated_iv, iv_residual,
                abs_iv_residual, residual_threshold, evaluation_state, reason_code,
                surfaced_direction, evidence_json)
               VALUES (?, ?, ?, ?, ?, 100, 'C', 0.5, ?, 95, ?, 105, ?, ?, ?, ?, 0.03,
                'SURFACED','LOCAL_IV_RESIDUAL_ABOVE_THRESHOLD','IV_RICH_LOCAL','{}');""",
            (scanner_run, ref_id, qid[100], underlying, EXPIRY, smile(100), smile(95), smile(105),
             chord, smile(100) - chord, smile(100) - chord)).lastrowid)

        def quote(k):
            return conn.execute("SELECT bid, ask FROM option_quotes WHERE id=?", (qid[k],)).fetchone()

        legs, pricing = [], []
        for k, side, qty in ((95, "BUY", 1), (100, "SELL", 2), (105, "BUY", 1)):
            q = quote(k)
            entry = q["ask"] if side == "BUY" else q["bid"]
            legs.append({"reference_contract_id": ref_id, "option_quote_id": qid[k], "strike": float(k),
                         "right": "C", "quantity": qty, "side": side, "shares_per_contract": 100.0})
            pricing.append({"option_quote_id": qid[k], "side": side, "quantity": qty, "entry_price": entry})
        debit = sum((p["entry_price"] if p["side"] == "BUY" else -p["entry_price"]) * p["quantity"] * 100
                    for p in pricing)
        max_loss_minor = int(round(max(debit, 0) * 100))
        proposal_id = int(conn.execute(
            """INSERT INTO shadow_structure_proposals (hypothesis_evaluation_id, research_run_id,
                target_reference_contract_id, underlying, expiration, right, target_strike,
                builder_family_id, builder_version, builder_rule_version, anomaly_direction,
                proposal_state, reason_code, structure_id, structure_version, structure_json,
                entry_pricing_json, risk_currency, max_theoretical_loss_minor, risk_basis, created_at)
               VALUES (?, ?, ?, ?, ?, 'C', 100, 'LOCAL_IV_BUTTERFLY_EXPRESSION_V1','1.0.0',
                'LOCAL_IV_BUTTERFLY_RULES_V1','IV_RICH_LOCAL','PROPOSED','DEFINED_RISK_STRUCTURE_CONSTRUCTED',
                'LONG_1_2_1_BUTTERFLY','1.0.0', ?, ?, 'USD', ?,
                'THEORETICAL_EXPIRY_PAYOFF_USING_CONSERVATIVE_BID_ASK_ENTRY','2026-09-01T18:00:07Z');""",
            (eval_id, run_id, ref_id, underlying, EXPIRY,
             json.dumps({"structure_id": "LONG_1_2_1_BUTTERFLY", "legs": legs}, sort_keys=True),
             json.dumps({"pricing_basis": "BUY_AT_ASK_SELL_AT_BID", "legs": pricing}, sort_keys=True),
             max_loss_minor)).lastrowid)
        if with_v2:
            v2_run = int(conn.execute(
                """INSERT INTO local_surface_residual_v2_runs (research_run_id, model_family_id,
                    model_version, fit_spec_version, config_hash, config_json, observed_at,
                    structural_input_count, reference_mapped_count, evaluable_count)
                   VALUES (?, 'LOCAL_QUADRATIC_LOO','1','1',?, '{}', ?, 9, 9, 9);""",
                (run_id, "b" * 64, CAPTURED)).lastrowid)
            conn.execute(
                """INSERT INTO local_surface_residual_v2_observations (model_run_id, reference_contract_id,
                    option_quote_id, underlying, expiration, strike, right, delta, implied_volatility,
                    usable_strike_count, fit_point_count, fit_dof, fitted_iv, loo_residual,
                    abs_loo_residual, observation_state, reason_code, evidence_json)
                   VALUES (?, ?, ?, ?, ?, 100, 'C', 0.5, ?, 8, 8, 5, ?, ?, ?,
                    'EVALUATED_OBSERVATIONAL','LOO_QUADRATIC_RESIDUAL_MEASURED','{}');""",
                (v2_run, ref_id, qid[100], underlying, EXPIRY, smile(100), 0.205, 0.035, 0.035))
        conn.commit()
        return {"proposal_id": proposal_id, "run_id": run_id, "qid": qid, "snapshot_id": snap_id}
    finally:
        conn.close()


def test_idea_shows_three_models_side_by_side(db_path):
    ids = seed_scenario(db_path, with_v2=True)
    ideas, errors, session = load_current_ideas(db_path=db_path)
    assert errors == [] and session == SESSION
    assert len(ideas) == 1
    idea = ideas[0]
    assert idea.proposal_id == ids["proposal_id"]
    assert tuple(idea.judgements) == MODEL_ORDER
    assert idea.strikes == (95.0, 100.0, 105.0) and idea.target_strike == 100.0
    assert idea.dte == 17
    for model_id in MODEL_ORDER:
        j = idea.judgements[model_id]
        assert j.available, (model_id, j.reason)
        # the market has the middle strike rich; every model sees it as too high
        assert j.fair_iv_by_strike[100.0] < smile(100)
    assert idea.available == 3
    # per-model numbers differ; they are not blended
    edges = {m: idea.judgements[m].net_edge_usd for m in MODEL_ORDER}
    assert len(set(round(v, 6) for v in edges.values())) == 3
    assert idea.favouring == sum(1 for m in MODEL_ORDER if idea.judgements[m].favours)
    assert idea.profile is not None and 0.0 < idea.profile.p_profit < 1.0
    assert idea.net_debit_usd > 0 and idea.max_loss_usd == pytest.approx(idea.net_debit_usd)
    assert idea.admission_decision is None  # nothing admitted yet


def test_unavailable_model_is_explained_not_zeroed(db_path):
    seed_scenario(db_path, with_v2=False)
    ideas, _, _ = load_current_ideas(db_path=db_path)
    j = ideas[0].judgements[MODEL_V2]
    assert not j.available and "No V2 observation" in j.reason
    assert ideas[0].available == 2


def test_v1_fair_iv_is_the_scanner_chord(db_path):
    seed_scenario(db_path)
    idea = load_current_ideas(db_path=db_path)[0][0]
    chord = (smile(95) + smile(105)) / 2
    assert idea.judgements[MODEL_V1].fair_iv_by_strike[100.0] == pytest.approx(chord)


def test_one_unscorable_proposal_does_not_hide_the_rest(db_path):
    good = seed_scenario(db_path)
    bad = seed_scenario(db_path, underlying="MSFT", omit_iv_strike=100)
    ideas, errors, _ = load_current_ideas(db_path=db_path)
    assert [i.proposal_id for i in ideas] == [good["proposal_id"]]
    assert len(errors) == 1 and errors[0][0] == bad["proposal_id"]


def test_ranking_prefers_more_agreeing_models_then_edge_per_risk(db_path):
    from src.decision.trade_ideas import rank_ideas

    seed_scenario(db_path, with_v2=True)
    base = load_current_ideas(db_path=db_path)[0][0]
    import dataclasses

    worse = dataclasses.replace(base, proposal_id=2, underlying="ZZZ", favouring=1,
                                median_net_edge_to_max_loss=9.0)
    better = dataclasses.replace(base, proposal_id=3, underlying="AAA", favouring=3,
                                 median_net_edge_to_max_loss=0.1)
    tie_low = dataclasses.replace(base, proposal_id=4, underlying="BBB", favouring=3,
                                  median_net_edge_to_max_loss=0.05)
    none = dataclasses.replace(base, proposal_id=5, underlying="CCC", favouring=3,
                               median_net_edge_to_max_loss=None)
    ranked = rank_ideas([worse, none, tie_low, better])
    assert [i.underlying for i in ranked] == ["AAA", "BBB", "CCC", "ZZZ"]


def test_score_proposal_matches_loaded_idea(db_path):
    ids = seed_scenario(db_path, with_v2=True)
    a = score_proposal(ids["proposal_id"], db_path=db_path)
    b = load_current_ideas(db_path=db_path)[0][0]
    for m in MODEL_ORDER:
        assert a.judgements[m].net_edge_usd == pytest.approx(b.judgements[m].net_edge_usd)


def test_track_record_is_empty_before_any_outcome(db_path):
    seed_scenario(db_path)
    records, resolved = model_track_record(db_path=db_path)
    assert resolved == 0
    assert all(r.n_favoured == 0 and r.hit_rate is None for r in records.values())


def test_track_record_counts_only_trades_the_model_favoured_at_entry(db_path):
    """One winner (pins at the middle strike) and one loser (collapses below
    the lower wing); both were favoured by the models at entry."""
    from src.research.shadow_admission import admit_shadow_proposals
    from src.research.shadow_expiry_outcome_v1 import record_shadow_expiry_outcomes
    from tests._shadow_admission_seed import fx

    win = seed_scenario(db_path, with_v2=True, underlying="AAPL")
    lose = seed_scenario(db_path, with_v2=True, underlying="MSFT")
    entry_ideas = {i.underlying: i for i in load_current_ideas(db_path=db_path)[0]}
    admit_shadow_proposals(
        fx=fx(), proposal_ids=[win["proposal_id"], lose["proposal_id"]], db_path=db_path
    )

    conn = get_connection(db_path)
    try:
        for underlying, price in (("AAPL", 100.0), ("MSFT", 80.0)):
            run = int(conn.execute(
                """INSERT INTO research_runs (cohort_id, preregistration_hash, code_git_sha,
                    started_at, ended_at, us_session_date, us_session_state, status)
                   VALUES ('T','h','s','2026-09-18T19:45:00Z','2026-09-18T19:45:00Z',
                    '2026-09-18','INTRADAY','COMPLETED');""").lastrowid)
            conn.execute(
                """INSERT INTO market_snapshots (captured_at, underlying, provider, research_run_id,
                    us_session_date, us_session_state, underlying_source, fx_source, underlying_price)
                   VALUES ('2026-09-18T19:45:00Z', ?, 'THETADATA', ?, '2026-09-18', 'INTRADAY',
                    'FETCHED', 'UNKNOWN', ?);""", (underlying, run, price))
        after = int(conn.execute(
            """INSERT INTO research_runs (cohort_id, preregistration_hash, code_git_sha,
                started_at, ended_at, us_session_date, us_session_state, status)
               VALUES ('T','h','s','2026-09-21T14:00:00Z','2026-09-21T14:00:00Z',
                '2026-09-21','INTRADAY','COMPLETED');""").lastrowid)
        conn.commit()
    finally:
        conn.close()
    res = record_shadow_expiry_outcomes(research_run_id=after, db_path=db_path)
    assert res.resolved_written == 2

    conn = get_connection(db_path)
    try:
        pnl = {
            r["underlying"]: r["estimated_net_pnl_usd_minor"] / 100.0
            for r in conn.execute(
                """SELECT sc.underlying, o.estimated_net_pnl_usd_minor
                   FROM shadow_expiry_outcomes_v1 o JOIN shadow_candidates sc ON sc.id = o.candidate_id""")
        }
    finally:
        conn.close()
    assert pnl["AAPL"] > 0 > pnl["MSFT"]

    records, resolved = model_track_record(db_path=db_path)
    assert resolved == 2
    for model_id in MODEL_ORDER:
        both = all(entry_ideas[u].judgements[model_id].favours for u in ("AAPL", "MSFT"))
        rec = records[model_id]
        assert rec.n_scored == 2
        if both:
            assert (rec.n_favoured, rec.wins) == (2, 1)
            assert rec.hit_rate == 0.5
            assert rec.mean_net_pnl_usd == pytest.approx((pnl["AAPL"] + pnl["MSFT"]) / 2)
            assert rec.hit_rate_ci is not None and rec.mean_ci is not None
    # at least one model must have favoured both, or this test proves nothing
    assert any(
        all(entry_ideas[u].judgements[m].favours for u in ("AAPL", "MSFT")) for m in MODEL_ORDER
    )


# --------------------------------------------------------------------------
# Page helpers and the page itself
# --------------------------------------------------------------------------
def test_table_rows_put_each_model_in_its_own_column(db_path):
    from src.ui.trade_ideas_page import MODEL_LABELS, ideas_to_rows

    seed_scenario(db_path, with_v2=True)
    idea = load_current_ideas(db_path=db_path)[0][0]
    row = ideas_to_rows([idea])[0]
    assert row["Underlying"] == "AAPL" and row["Trade"] == "Long fly 95/100/105 call"
    assert row["Expiry"] == "2026-09-18 (17d)"
    for model_id in MODEL_ORDER:
        cell = row[MODEL_LABELS[model_id]]
        assert cell[0] in "✓≈✗" and "$" in cell
    assert row["Models seeing edge"] == f"{idea.favouring}/3"
    assert row["Status"] == "Not yet decided"
    assert row["Profit-zone odds*"].endswith("%")
    assert " – " in row["Profit zone at expiry"]


def test_unavailable_model_cell_and_formatting():
    from src.ui.trade_ideas_page import eu, usd, verdict_cell
    from src.decision.trade_ideas import unavailable

    assert verdict_cell(unavailable(MODEL_V2, "x")) == "n/a"
    assert eu(12345.678, 2) == "12.345,68"
    assert usd(-30.1, signed=True) == "−$30" and usd(12.4, signed=True) == "+$12"
    assert usd(None) == "—"


def test_evidence_banner_never_overstates():
    from src.decision.trade_ideas import ModelRecord
    from src.ui.trade_ideas_page import evidence_banner, record_rows

    empty = {m: ModelRecord(m, 0, 0, 0, None, None, None, None) for m in MODEL_ORDER}
    tone, text = evidence_banner(empty, 0)
    assert tone == "warning" and "No trade has been tested" in text
    tone, text = evidence_banner(empty, 4)
    assert "untested" in text and "favoured" in text
    rows = record_rows(empty)
    assert rows[0]["Hit rate (95% interval)"] == "—" and rows[0]["Mean net P&L per trade"] == "—"


def test_trade_ideas_is_the_first_page_and_renders(db_path, monkeypatch):
    import pathlib
    from streamlit.testing.v1 import AppTest

    seed_scenario(db_path, with_v2=True)
    monkeypatch.setenv("CHRISTIANIA_DB_PATH", str(db_path))
    import streamlit as st

    st.cache_data.clear()
    root = pathlib.Path(__file__).resolve().parents[1]
    app = AppTest.from_file(str(root / "app.py"), default_timeout=90)
    app.run(timeout=90)
    assert not app.exception, app.exception
    assert app.sidebar.radio[0].options[0].endswith("Trade Ideas")
    assert app.sidebar.radio[0].value.endswith("Trade Ideas")
    page_text = " ".join(m.value for m in app.markdown) + " ".join(c.value for c in app.caption)
    assert "Trade Ideas" in page_text
    assert [m.label for m in app.metric][:4] == ["Session", "Trades scored", "2+ models see edge", "Resolved at expiry"]
    assert any("No trade has been tested" in w.value for w in app.warning)


def test_track_record_uses_only_the_current_outcome_revision(db_path):
    """An outcome first recorded UNRESOLVED (no expiry snapshot yet) and later
    superseded by a RESOLVED revision must be counted once, as RESOLVED."""
    from src.research.shadow_admission import admit_shadow_proposals
    from src.research.shadow_expiry_outcome_v1 import record_shadow_expiry_outcomes
    from tests._shadow_admission_seed import fx

    ids = seed_scenario(db_path, with_v2=True)
    admit_shadow_proposals(fx=fx(), proposal_ids=[ids["proposal_id"]], db_path=db_path)
    conn = get_connection(db_path)
    try:
        after = int(conn.execute(
            """INSERT INTO research_runs (cohort_id, preregistration_hash, code_git_sha,
                started_at, ended_at, us_session_date, us_session_state, status)
               VALUES ('T','h','s','2026-09-21T14:00:00Z','2026-09-21T14:00:00Z',
                '2026-09-21','INTRADAY','COMPLETED');""").lastrowid)
        conn.commit()
    finally:
        conn.close()
    record_shadow_expiry_outcomes(research_run_id=after, db_path=db_path)  # revision 1: UNRESOLVED
    records, resolved = model_track_record(db_path=db_path)
    assert resolved == 0 and all(r.n_favoured == 0 for r in records.values())

    conn = get_connection(db_path)
    try:
        run = int(conn.execute(
            """INSERT INTO research_runs (cohort_id, preregistration_hash, code_git_sha,
                started_at, ended_at, us_session_date, us_session_state, status)
               VALUES ('T','h','s','2026-09-18T19:45:00Z','2026-09-18T19:45:00Z',
                '2026-09-18','INTRADAY','COMPLETED');""").lastrowid)
        conn.execute(
            """INSERT INTO market_snapshots (captured_at, underlying, provider, research_run_id,
                us_session_date, us_session_state, underlying_source, fx_source, underlying_price)
               VALUES ('2026-09-18T19:45:00Z','AAPL','THETADATA',?,'2026-09-18','INTRADAY','FETCHED','UNKNOWN',100.0);""",
            (run,))
        conn.commit()
    finally:
        conn.close()
    record_shadow_expiry_outcomes(research_run_id=after, db_path=db_path)  # revision 2: RESOLVED
    conn = get_connection(db_path)
    try:
        revisions = [(r["revision"], r["outcome_state"]) for r in conn.execute(
            "SELECT revision, outcome_state FROM shadow_expiry_outcomes_v1 ORDER BY revision")]
    finally:
        conn.close()
    assert revisions == [(1, "UNRESOLVED"), (2, "RESOLVED")]
    records, resolved = model_track_record(db_path=db_path)
    assert resolved == 1  # not 2, and the UNRESOLVED revision is not counted

    # Late, later-captured expiry-session data supersedes the RESOLVED revision
    # (the pin collapses to 80 in the final sample).  Both revisions are RESOLVED;
    # only the latest may count.
    conn = get_connection(db_path)
    try:
        conn.execute(
            """INSERT INTO market_snapshots (captured_at, underlying, provider, research_run_id,
                us_session_date, us_session_state, underlying_source, fx_source, underlying_price)
               VALUES ('2026-09-18T19:50:00Z','AAPL','THETADATA',?,'2026-09-18','INTRADAY','FETCHED','UNKNOWN',80.0);""",
            (run,))
        conn.commit()
    finally:
        conn.close()
    record_shadow_expiry_outcomes(research_run_id=after, db_path=db_path)  # revision 3: RESOLVED
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT revision, outcome_state, estimated_net_pnl_usd_minor AS pnl FROM shadow_expiry_outcomes_v1 ORDER BY revision"
        ).fetchall()
    finally:
        conn.close()
    assert [(r["revision"], r["outcome_state"]) for r in rows] == [(1, "UNRESOLVED"), (2, "RESOLVED"), (3, "RESOLVED")]
    assert rows[1]["pnl"] > 0 > rows[2]["pnl"]

    records, resolved = model_track_record(db_path=db_path)
    assert resolved == 1
    idea = score_proposal(ids["proposal_id"], db_path=db_path)
    assert any(j.favours for j in idea.judgements.values()), "test needs a favouring model"
    for model_id, judgement in idea.judgements.items():
        rec = records[model_id]
        if judgement.favours:
            assert (rec.n_favoured, rec.wins) == (1, 0)  # the loss, counted once
            assert rec.mean_net_pnl_usd == pytest.approx(rows[2]["pnl"] / 100.0)
