from __future__ import annotations

from dataclasses import replace

from src.research.prospective_paper_outcome_v1 import (
    VERSION, OptionLeg, LegQuote, Phase, PaperPackage, evaluate
)

ENTRY = "2026-10-12T15:00:00Z"
EXIT = "2026-10-12T16:00:00Z"
EXPIRY = "2026-11-20"


def frame(*, exit_phase=False):
    t="2026-10-12T15:59:55Z" if exit_phase else "2026-10-12T14:59:55Z"
    cap="2026-10-12T15:59:57Z" if exit_phase else "2026-10-12T14:59:57Z"
    if exit_phase:
        return (
            LegQuote("C100","C","100",EXPIRY,"100","8","9","20","20",
                     t,t,t,"src:e1","exit:1",cap,"THETADATA"),
            LegQuote("C105","C","105",EXPIRY,"100","2","3","20","20",
                     t,t,t,"src:e2","exit:1",cap,"THETADATA"),
        )
    return (
        LegQuote("C100","C","100",EXPIRY,"100","5","6","20","20",
                 t,t,t,"src:1","entry:1",cap,"THETADATA"),
        LegQuote("C105","C","105",EXPIRY,"100","3","4","20","20",
                 t,t,t,"src:2","entry:1",cap,"THETADATA"),
    )


def candidate():
    return PaperPackage(
        candidate_id=12, strategy_id="S03", frozen_signal_version="SYNTHETIC_V1",
        preregistration_hash="a"*64, prospective_session="2026-10-12",
        legs=(
            OptionLeg("C100","C","100",EXPIRY,"100","BUY",1),
            OptionLeg("C105","C","105",EXPIRY,"100","SELL",1),
        ),
        entry=Phase(
            ENTRY, frame(), "ENTRY", "1.20",
            "2026-10-12T14:58:00Z", "SYNTHETIC_FX_VERIFIED_FIXTURE",
            "6", "2", "1", "SYNTHETIC_COST_FIXTURE",
            "CLOCK_LIVE_VERIFIED_FIXTURE"),
        exit=Phase(
            EXIT,frame(exit_phase=True),"EXIT","1.25",
            "2026-10-12T15:59:00Z","SYNTHETIC_FX_VERIFIED_FIXTURE",
            "6","3","1","SYNTHETIC_COST_FIXTURE",
            "CLOCK_LIVE_VERIFIED_FIXTURE"),
        exit_rule_id="FROZEN_PREDECLARED_EXIT_V1"
    )


def mutated_quote(p, *, phase="entry", index=0, **fields):
    old=getattr(p,phase)
    q=list(old.quotes)
    q[index]=replace(q[index],**fields)
    return replace(p,**{phase:replace(old,quotes=tuple(q))})


def test_deterministic_correct_two_fx_cashflows_and_round_trip_costs():
    p=candidate()
    r=evaluate(p)
    assert r.status=="PAPER_LEG_QUOTE_STRESS_ONLY"
    assert r.entry_cashflow_usd_minor==-30000
    assert r.exit_cashflow_usd_minor==50000
    assert r.gross_pnl_usd_minor==20000
    assert r.applied_cost_usd_minor==1900
    assert r.estimated_net_pnl_usd_minor==18100
    assert r.estimated_net_pnl_eur_minor==13450
    assert r.validated_package_outcome is False
    assert r.outcome_eligible is False
    assert r.usable_for_strategy_edge is False
    assert r.reasons==("NO_INDEPENDENT_EXECUTABLE_PACKAGE_FILL_VERIFICATION",)
    assert evaluate(p)==r
    assert r.evidence_hash_sha256 and len(r.evidence_hash_sha256)==64
    assert VERSION.endswith("V1")


def test_no_mid_and_no_package_fills_even_if_economically_positive():
    p=candidate()
    r=evaluate(p)
    # Midpoint math: entry 5.5-3.5 => -200, exit 8.5-2.5 => +600;
    # correct quote-side entry -300 and exit +500 instead.
    assert r.gross_pnl_usd_minor==20000
    assert r.gross_pnl_usd_minor!=40000
    assert not r.outcome_eligible


def test_source_stale_on_one_leg_denied():
    p=mutated_quote(candidate(),quote_at="2026-10-12T14:59:40Z")
    r=evaluate(p)
    assert r.status=="NOT_EVALUABLE"
    assert "STALE_LEG_OR_SNAPSHOT" in r.reasons
    assert r.estimated_net_pnl_usd_minor is None
    assert not r.outcome_eligible


def test_future_source_denied():
    p=mutated_quote(candidate(),quote_at="2026-10-12T15:00:01Z")
    r=evaluate(p)
    assert "LOOKAHEAD_OR_FUTURE_SOURCE" in r.reasons
    assert r.status=="NOT_EVALUABLE"


def test_undersized_buy_entry_and_buy_exit_denied():
    p=mutated_quote(candidate(),ask_size="0")
    assert "MISSING_BUY_SIDE_SIZE" in evaluate(p).reasons
    p=mutated_quote(candidate(),phase="exit",index=1,ask_size="0")
    assert "MISSING_BUY_SIDE_SIZE" in evaluate(p).reasons


def test_mismatched_contract_expiry_and_snapshot_denied():
    p=mutated_quote(candidate(),multiplier="10")
    assert "QUOTE_CONTRACT_IDENTITY_DRIFT" in evaluate(p).reasons
    p=mutated_quote(candidate(),index=1,snapshot_id="unrelated-snapshot")
    assert "LEGS_NOT_FROM_ONE_SNAPSHOT" in evaluate(p).reasons
    p=mutated_quote(candidate(),right="P")
    assert "QUOTE_CONTRACT_IDENTITY_DRIFT" in evaluate(p).reasons


def test_missing_cost_and_fx_provenance_denied():
    p=candidate()
    p=replace(p,entry=replace(p.entry,fee_provenance="",fx_source=""))
    r=evaluate(p)
    assert "COST_OR_FX_PROVENANCE_MISSING" in r.reasons
    assert r.status=="NOT_EVALUABLE"
    p=candidate()
    p=replace(p,entry=replace(p.entry,fx_observed_at="2026-10-12T15:01:00Z"))
    assert "FX_TIMESTAMP_FUTURE_OR_STALE" in evaluate(p).reasons


def test_unverified_timestamp_reference_denied():
    p=candidate()
    p=replace(p,entry=replace(p.entry,timestamp_validation_ref=""))
    assert "INDEPENDENT_LIVE_TIMESTAMP_VERIFICATION_MISSING" in evaluate(p).reasons


def test_wrong_order_no_preregistration_denied():
    p=candidate()
    p=replace(p,exit=replace(p.exit,decision_at="2026-10-12T14:50:00Z"))
    assert "EXIT_NOT_AFTER_ENTRY" in evaluate(p).reasons
    p=replace(candidate(),preregistration_hash="")
    assert "PREREGISTRATION_HASH_NOT_FROZEN" in evaluate(p).reasons
    p=replace(candidate(),prospective_session="2026-10-13")
    assert "PROSPECTIVE_SESSION_AFTER_ENTRY" in evaluate(p).reasons


def test_naive_time_crossed_quote_or_negative_cost_denied():
    p=mutated_quote(candidate(),quote_at="2026-10-12T14:59:55")
    assert "QUOTE_PRICE_TIME_OR_COST_UNPARSEABLE" in evaluate(p).reasons
    p=mutated_quote(candidate(),ask="4")
    assert "INVALID_BID_ASK_OR_DEPTH" in evaluate(p).reasons
    p=candidate()
    p=replace(p,exit=replace(p.exit,taxes_usd="-1"))
    assert "NEGATIVE_COST_OR_INVALID_FX" in evaluate(p).reasons


def test_incomplete_quote_or_duplicate_contract_denied():
    p=candidate()
    p=replace(p,exit=replace(p.exit,quotes=p.exit.quotes[:1]))
    assert "INCOMPLETE_QUOTE_POPULATION" in evaluate(p).reasons
    p=candidate()
    p=replace(p,legs=(p.legs[0],p.legs[0]))
    assert "DUPLICATE_STRUCTURE_CONTRACT_ID" in evaluate(p).reasons




def test_no_quote_used_twice_as_independent_source():
    p=candidate()
    p=mutated_quote(p,index=1,source_id=p.entry.quotes[0].source_id)
    assert "DUPLICATE_SOURCE_QUOTE_ID" in evaluate(p).reasons


def test_expired_contract_cannot_be_closed_with_post_expiry_quotes():
    p=candidate()
    past=replace(p,legs=tuple(replace(l,expiration="2026-10-11") for l in p.legs))
    past=replace(past,entry=replace(past.entry,quotes=tuple(
        replace(q,expiration="2026-10-11") for q in p.entry.quotes)),
        exit=replace(past.exit,quotes=tuple(
            replace(q,expiration="2026-10-11") for q in p.exit.quotes)))
    assert "EXIT_AFTER_OPTION_EXPIRATION" in evaluate(past).reasons



def test_losses_are_kept_not_filtered_out():
    p=candidate()
    # Both exit legs move adversely; DO NOT filter trades by P&L.
    p=mutated_quote(p,phase="exit",index=0,bid="2",ask="3")
    p=mutated_quote(p,phase="exit",index=1,bid="4",ask="5")
    r=evaluate(p)
    assert r.status=="PAPER_LEG_QUOTE_STRESS_ONLY"
    assert r.gross_pnl_usd_minor==-60000
    assert r.estimated_net_pnl_usd_minor==-61900
    assert r.estimated_net_pnl_eur_minor==-50550
    assert not r.outcome_eligible


def test_adverse_slippage_can_erase_gross_profit():
    p=candidate()
    p=replace(p,exit=replace(p.exit,extra_slippage_usd="220"))
    r=evaluate(p)
    assert r.gross_pnl_usd_minor==20000
    assert r.estimated_net_pnl_usd_minor==-3600
    assert r.estimated_net_pnl_eur_minor < 0
    assert not r.usable_for_strategy_edge

def test_quote_conversion_not_a_live_trade_or_validated_package():
    p=candidate()
    r=evaluate(p).as_dict()
    assert r["validated_package_outcome"] is False
    assert r["outcome_eligible"] is False
    assert r["usable_for_strategy_edge"] is False
    assert "NO_INDEPENDENT_EXECUTABLE_PACKAGE_FILL_VERIFICATION" in r["reasons"]
