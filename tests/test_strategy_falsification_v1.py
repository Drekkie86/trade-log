"""Independent hand-priced fixtures for deterministic Stage-0 strategy maths.

Pure standard-library unittest: deliberately works even when pytest is absent.
Nothing in this test suite accesses a provider, account, broker or database.
"""
import json
import unittest
from decimal import Decimal as D

from src.research.strategy_falsification_v1 import (
    CATALOGUE, LEGACY_REVERSE_ID, Leg, Structure,
    QuoteCostPolicy, catalogue_without_quotes, evaluate, from_shadow_proposal,
)

T = "2026-10-12T15:00:00Z"
Q = "2026-10-12T14:59:45Z"
EXP = "2026-11-20"


def opt(kind, strike, side, bid, ask, qty=1, *,
        quote_at=Q, bid_size="20", ask_size="20", multiplier="100", expiration=EXP):
    return Leg(kind, side, qty, D(multiplier), D(strike), expiration,
               None if bid is None else D(bid),
               None if ask is None else D(ask),
               quote_at,
               None if bid_size is None else D(bid_size),
               None if ask_size is None else D(ask_size))


def share(side="BUY", bid="99", ask="100", quantity=100):
    return Leg("STOCK", side, quantity, D("1"), None, None,
               D(bid), D(ask), Q, D("1000"), D("1000"))


POLICY = QuoteCostPolicy(
    option_cost_per_contract_side_usd=D("3"),
    stock_round_trip_cost_usd=D("2"),
    eur_to_usd=D("1.10"),
    cost_provenance="SYNTHETIC_ASSUMED_COST_TEST_ONLY",
    fx_provenance="SYNTHETIC_FX_TEST_ONLY",
    max_quote_age_seconds=60,
    verified_share_inventory=False,
    bankroll_eur=D("500"),  # fixture allocation; not a system ceiling
    max_leg_quote_skew_seconds=60,  # fixture-only, not a production threshold
    additional_round_trip_cost_usd=D("0"), # fixture-only, NOT proof of free slippage
    tax_cost_usd=D("0"), # fixture-only, not a tax determination
    fx_observed_at=Q,
)


def struct(k, *legs):
    return Structure(k, "FIXTURE_SIGNAL_V1_NOT_VALIDATED", T, tuple(legs))


def examples():
    return {
        "S01": struct("S01", share(), opt("CALL", 105, "SELL", "3", "4")),
        "S02": struct("S02", share(), opt("PUT", 95, "BUY", "1", "2")),
        "S03": struct("S03", opt("CALL", 100, "BUY", "5", "6"),
                       opt("CALL", 105, "SELL", "3", "4")),
        "S04": struct("S04", opt("PUT", 105, "BUY", "5", "6"),
                       opt("PUT", 100, "SELL", "3", "4")),
        "S05": struct("S05", share(), opt("PUT", 95, "BUY", "1", "2"),
                       opt("CALL", 105, "SELL", "3", "4")),
        "S06": struct("S06", opt("CALL", 100, "BUY", "4", "5"),
                       opt("PUT", 100, "BUY", "3", "4")),
        "S07": struct("S07", opt("PUT", 95, "BUY", "1", "2"),
                       opt("CALL", 105, "BUY", "2", "3")),
        "S08": struct("S08", opt("CALL", 95, "BUY", "7", "8"),
                       opt("CALL", 100, "SELL", "5", "6", qty=2),
                       opt("CALL", 105, "BUY", "2", "3")),
        "S09": struct("S09", opt("PUT", 90, "BUY", "0.5", "1"),
                       opt("PUT", 95, "SELL", "2", "2.5"),
                       opt("CALL", 105, "SELL", "2", "2.5"),
                       opt("CALL", 110, "BUY", "0.5", "1")),
        "S10": struct("S10", opt("PUT", 95, "BUY", "1.5", "2"),
                       opt("PUT", 100, "SELL", "3", "4"),
                       opt("CALL", 100, "SELL", "3", "4"),
                       opt("CALL", 105, "BUY", "1.5", "2")),
        "X11": struct("X11", opt("CALL", 100, "BUY", "5", "6"),
                       opt("CALL", 105, "SELL", "3", "4")),
    }


class StrategyStage0Tests(unittest.TestCase):
    def test_all_11_explicit_catalogue_rows_and_no_fake_edge_claim(self):
        self.assertEqual(len(CATALOGUE), 11)
        self.assertEqual(set(examples()), set(CATALOGUE))
        rows = catalogue_without_quotes()
        self.assertEqual(len(rows), 11)
        self.assertTrue(all(x["status"] == "UNTESTED_NO_QUOTE_OR_OUTCOME_EVIDENCE"
                            for x in rows))

    def test_all_synthetic_structures_pass_shape_rules(self):
        for name, scenario in examples().items():
            with self.subTest(name=name):
                r = evaluate(scenario, POLICY)
                self.assertNotIn(r.state, ("FAILED_STRUCTURE", "UNSCORABLE"))
                self.assertIsNotNone(r.entry_cashflow_usd)

    def test_verticals_have_exact_payoff_and_cost_math(self):
        for name, breakeven in (("S03", "103.00"), ("S04", "102.00"),
                                ("X11", "103.00")):
            with self.subTest(name=name):
                r = evaluate(examples()[name], POLICY)
                self.assertEqual(r.gross_max_loss_usd, "300.00")
                self.assertEqual(r.gross_max_profit_usd, "200.00")
                self.assertEqual(r.entry_cashflow_usd, "-300.00")
                self.assertEqual(r.round_trip_cost_usd, "12.00")
                self.assertEqual(r.conservative_capital_eur, "283.64")
                self.assertEqual(r.breakevens_usd, (breakeven,))
                self.assertEqual(r.state, "INDICATIVELY_AFFORDABLE_NOT_EXECUTABLE")

    def test_straddle_and_strangle(self):
        s = evaluate(examples()["S06"], POLICY)
        self.assertEqual(s.gross_max_loss_usd, "900.00")
        self.assertEqual(s.gross_max_profit_usd, None)
        self.assertTrue(s.unlimited_profit)
        self.assertEqual(s.state, "OVER_CAP")
        t = evaluate(examples()["S07"], POLICY)
        self.assertEqual(t.gross_max_loss_usd, "500.00")
        self.assertTrue(t.unlimited_profit)
        self.assertEqual(t.breakevens_usd, ("90.00", "110.00"))
        self.assertEqual(t.state, "INDICATIVELY_AFFORDABLE_NOT_EXECUTABLE")

    def test_long_butterfly_equal_wings_four_contract_sides(self):
        r = evaluate(examples()["S08"], POLICY)
        self.assertEqual(r.gross_max_loss_usd, "100.00")
        self.assertEqual(r.gross_max_profit_usd, "400.00")
        self.assertEqual(r.round_trip_cost_usd, "24.00")
        self.assertEqual(r.breakevens_usd, ("96.00", "104.00"))
        self.assertEqual(r.conservative_capital_eur, "112.73")

    def test_iron_condor_fly_bounded_loss(self):
        for key in ("S09", "S10"):
            with self.subTest(key=key):
                r = evaluate(examples()[key], POLICY)
                self.assertEqual(r.entry_cashflow_usd, "200.00")
                self.assertEqual(r.gross_max_loss_usd, "300.00")
                self.assertEqual(r.gross_max_profit_usd, "200.00")
                self.assertEqual(r.round_trip_cost_usd, "24.00")
                self.assertEqual(r.conservative_capital_eur, "294.55")
                self.assertFalse(r.unlimited_profit)
                self.assertEqual(r.state, "INDICATIVELY_AFFORDABLE_NOT_EXECUTABLE")

    def test_stock_hedges_reference_only_even_with_trading_quote(self):
        x = examples()
        for key in ("S01", "S02", "S05"):
            with self.subTest(key=key):
                r = evaluate(x[key], POLICY)
                self.assertEqual(r.state, "REFERENCE_HEDGE_ONLY")
                self.assertIn("OWNED_SHARE_INVENTORY_UNVERIFIED", r.reasons)
                self.assertIn("EXCEEDS_ALLOCATED_CAPITAL", r.reasons)
                self.assertTrue(D(r.conservative_capital_eur) > POLICY.bankroll_eur)
        self.assertEqual(evaluate(x["S01"], POLICY).gross_max_loss_usd, "9700.00")
        self.assertEqual(evaluate(x["S02"], POLICY).gross_max_loss_usd, "700.00")
        self.assertEqual(evaluate(x["S05"], POLICY).gross_max_loss_usd, "400.00")
        self.assertTrue(evaluate(x["S02"], POLICY).unlimited_profit)

    def test_no_mid_prices_quote_side_used_for_entry(self):
        r = evaluate(examples()["S03"], POLICY)
        self.assertEqual(r.entry_cashflow_usd, "-300.00")
        # Mid price would be 5.5-3.5 = 2.0, which must not be used.
        self.assertNotEqual(r.entry_cashflow_usd, "-200.00")

    def test_missing_size_or_cost_or_fx_never_approved(self):
        import dataclasses
        e = examples()["S03"]
        badsize = dataclasses.replace(e, legs=(
            dataclasses.replace(e.legs[0], ask_size=None), e.legs[1]))
        r = evaluate(badsize, POLICY)
        self.assertEqual(r.state, "INSUFFICIENT_EVIDENCE")
        self.assertIn("QUOTE_SIDE_SIZE_NOT_VERIFIED", r.reasons)
        r = evaluate(e, dataclasses.replace(POLICY,
            option_cost_per_contract_side_usd=None))
        self.assertIn("BROKER_OPTION_COST_MISSING", r.reasons)
        self.assertIsNone(r.conservative_capital_eur)
        r = evaluate(e, dataclasses.replace(POLICY, eur_to_usd=None))
        self.assertIn("FX_PROVENANCE_OR_RATE_MISSING", r.reasons)

    def test_future_quote_stale_quote_and_crossed_quote_blocked(self):
        import dataclasses
        e=examples()["S03"]
        for patch, reason in (
                ({"quote_at":"2026-10-12T15:00:01Z"}, "FUTURE_QUOTE_LEAKAGE"),
                ({"quote_at":"2026-10-12T14:40:00Z"}, "STALE_QUOTE"),
                ({"bid":D("8"),"ask":D("7")}, "CROSSED_OR_INVALID_QUOTE"),
                ({"ask_size":D("0")}, "INSUFFICIENT_VISIBLE_SIDE_SIZE")):
            with self.subTest(reason=reason):
                a=dataclasses.replace(e,legs=(dataclasses.replace(e.legs[0], **patch),e.legs[1]))
                r=evaluate(a,POLICY)
                self.assertIn(reason,r.reasons)
                self.assertNotEqual(r.state,"INDICATIVELY_AFFORDABLE_NOT_EXECUTABLE")

    def test_wrong_wings_wrong_signs_and_short_underlying_fail(self):
        import dataclasses
        e=examples()["S08"]
        malformed=dataclasses.replace(e,legs=(
            e.legs[0],e.legs[1],dataclasses.replace(e.legs[2], strike=D("106"))))
        self.assertEqual(evaluate(malformed,POLICY).state,"FAILED_STRUCTURE")
        bullish=examples()["S03"]
        inverted=dataclasses.replace(bullish,legs=(
            dataclasses.replace(bullish.legs[0],side="SELL"),
            dataclasses.replace(bullish.legs[1],side="BUY")))
        self.assertIn("INVALID_DIRECTIONAL_VERTICAL",evaluate(inverted,POLICY).reasons)
        a=dataclasses.replace(examples()["S01"],legs=(
            share(side="SELL"),examples()["S01"].legs[1]))
        self.assertEqual(evaluate(a,POLICY).state,"FAILED_STRUCTURE")

    def test_frozen_shadow_adapter_and_immutable_quote_crosscheck(self):
        source=examples()["S08"]
        data={"structure_id":"LONG_1_2_1_BUTTERFLY", "structure_version":"1.0.0",
              "legs":[dict(option_quote_id=i+1,reference_contract_id=i+1,
                           strike=str(l.strike),right="C",side=l.side,
                           quantity=l.quantity,
                           shares_per_contract=str(l.multiplier))
                      for i,l in enumerate(source.legs)]}
        quotes={i+1:{"bid":str(l.bid),"ask":str(l.ask),"expiration":EXP,
                      "quote_at":Q,"bid_size":"20","ask_size":"20", "right":"C", "strike":str(l.strike),"snapshot_id":9001}
                for i,l in enumerate(source.legs)}
        frozen={"pricing_basis":"BUY_AT_ASK_SELL_AT_BID",
                "legs":[{"option_quote_id":i+1,"entry_price":str(
                    l.ask if l.side=="BUY" else l.bid)}
                    for i,l in enumerate(source.legs)]}
        s=from_shadow_proposal(json.dumps(data),quotes,decision_at=T,
            signal_version="EXISTING_SHADOW_SCANNER_V1",
            frozen_entry_pricing_json=json.dumps(frozen))
        self.assertEqual(evaluate(s,POLICY).gross_max_loss_usd,"100.00")
        quotes[1]["ask"]="9"
        with self.assertRaisesRegex(ValueError,"FROZEN_ENTRY_DIFFERS"):
            from_shadow_proposal(json.dumps(data),quotes,decision_at=T,
                signal_version="EXISTING_SHADOW_SCANNER_V1",
                frozen_entry_pricing_json=json.dumps(frozen))

    def test_existing_reverse_butterfly_remains_reference_not_new_catalogue(self):
        s=struct(LEGACY_REVERSE_ID,
            opt("CALL",95,"SELL","6","7"),
            opt("CALL",100,"BUY","3","4",qty=2),
            opt("CALL",105,"SELL","2","3"))
        r=evaluate(s,POLICY)
        self.assertNotEqual(r.state,"FAILED_STRUCTURE")
        self.assertEqual(r.gross_max_loss_usd,"500.00")
        self.assertNotIn(LEGACY_REVERSE_ID,CATALOGUE)
        self.assertEqual(r.state, "LEGACY_REFERENCE_ONLY")

    def test_economically_dominated_structure_after_costs_is_rejected(self):
        import dataclasses
        s = examples()["S03"]
        expensive = dataclasses.replace(
            POLICY, additional_round_trip_cost_usd=D("250"))
        result = evaluate(s, expensive)
        self.assertEqual(result.gross_max_profit_usd, "200.00")
        self.assertEqual(result.as_dict()["net_max_profit_usd"], "-62.00")
        self.assertEqual(result.state, "ECONOMICALLY_DOMINATED_AFTER_ASSUMED_COSTS")
        self.assertIn("NON_POSITIVE_BEST_CASE_NET_EXPIRY_PAYOFF", result.reasons)
        self.assertNotEqual(result.state, "INDICATIVELY_AFFORDABLE_NOT_EXECUTABLE")

    def test_net_payoff_and_breakevens_include_costs_without_alpha_claim(self):
        r = evaluate(examples()["S03"], POLICY).as_dict()
        self.assertEqual(r["net_max_loss_usd"], "312.00")
        self.assertEqual(r["net_max_profit_usd"], "188.00")
        self.assertEqual(r["net_breakevens_usd"], ("103.12",))
        self.assertIn("NOT VERIFIED PACKAGE FILLS", r["disclaimer"])
        fly = evaluate(examples()["S08"], POLICY).as_dict()
        self.assertEqual(fly["net_max_loss_usd"], "124.00")
        self.assertEqual(fly["net_max_profit_usd"], "376.00")
        self.assertEqual(fly["net_breakevens_usd"], ("96.24", "103.76"))

    def test_missing_nonbroker_cost_or_fx_timestamp_fails_closed(self):
        import dataclasses
        for change, reason in (
            ({"additional_round_trip_cost_usd": None}, "SLIPPAGE_AND_FX_COST_BUDGET_MISSING"),
            ({"tax_cost_usd": None}, "TAX_COST_ASSUMPTION_MISSING"),
            ({"fx_observed_at": None}, "FX_OBSERVATION_TIME_MISSING"),
            ({"max_leg_quote_skew_seconds": None}, "QUOTE_SYNCHRONY_RULE_NOT_FROZEN"),
        ):
            with self.subTest(reason=reason):
                r=evaluate(examples()["S03"],dataclasses.replace(POLICY,**change))
                self.assertEqual(r.state,"INSUFFICIENT_EVIDENCE")
                self.assertIn(reason,r.reasons)

    def test_fx_future_and_quote_stagger_are_invalid(self):
        import dataclasses
        future=dataclasses.replace(POLICY,fx_observed_at="2026-10-12T15:00:01Z")
        self.assertIn("FUTURE_FX_RATE_LEAKAGE",evaluate(examples()["S03"],future).reasons)
        s=examples()["S03"]
        second=dataclasses.replace(s.legs[1],quote_at="2026-10-12T14:59:15Z")
        stagger=dataclasses.replace(s,legs=(s.legs[0],second))
        strict=dataclasses.replace(POLICY,max_leg_quote_skew_seconds=20)
        r=evaluate(stagger,strict)
        self.assertIn("LEGS_NOT_QUOTED_SYNCHRONOUSLY",r.reasons)
        self.assertEqual(r.state,"INSUFFICIENT_EVIDENCE")

    def test_expired_contract_and_negative_transaction_cost_fail(self):
        import dataclasses
        s=examples()["S03"]
        expired=dataclasses.replace(s,legs=tuple(
            dataclasses.replace(l,expiration="2026-10-01") for l in s.legs))
        self.assertIn("OPTION_EXPIRED_BEFORE_DECISION",evaluate(expired,POLICY).reasons)
        negative=dataclasses.replace(POLICY,additional_round_trip_cost_usd=D("-1"))
        self.assertIn("NEGATIVE_TRANSACTION_COST",evaluate(s,negative).reasons)

    def test_quote_identity_and_snapshot_mismatch_block_legacy_adapter(self):
        s=examples()["S08"]
        info={"structure_id":"LONG_1_2_1_BUTTERFLY","legs":[
            {"option_quote_id":i+1,"strike":str(l.strike),"right":"C",
             "side":l.side,"quantity":l.quantity,
             "shares_per_contract":"100"}
            for i,l in enumerate(s.legs)]}
        q={i+1:{"bid":str(l.bid),"ask":str(l.ask),"right":"C",
                 "strike":str(l.strike),"quote_at":Q,"expiration":EXP,
                 "snapshot_id":123} for i,l in enumerate(s.legs)}
        q[2]["snapshot_id"]=456
        with self.assertRaisesRegex(ValueError,"MULTI_SNAPSHOT"):
            from_shadow_proposal(json.dumps(info),q,decision_at=T,signal_version="TEST")
        q[2]["snapshot_id"]=123
        q[2]["right"]="P"
        with self.assertRaisesRegex(ValueError,"QUOTE_CONTRACT_IDENTITY_MISMATCH"):
            from_shadow_proposal(json.dumps(info),q,decision_at=T,signal_version="TEST")

    def test_no_assumed_timezone_and_no_static_arbitrage_promotion(self):
        import dataclasses
        s = examples()["S03"]
        naive_quote = dataclasses.replace(s, legs=(
            dataclasses.replace(s.legs[0], quote_at="2026-10-12T14:59:45"),
            s.legs[1]))
        r = evaluate(naive_quote, POLICY)
        self.assertEqual(r.state, "UNSCORABLE")
        self.assertEqual(r.reasons, ("QUOTE_TIMESTAMP_TZ_MISSING_OR_INVALID",))
        # A net-credit *bull debit spread* is suspicious even if individual
        # bid/ask pairs are not crossed. Do not call it a free edge.
        impossible = dataclasses.replace(s, legs=(
            dataclasses.replace(s.legs[0], bid=D("0.5"), ask=D("1")),
            s.legs[1]))
        x = evaluate(impossible, POLICY)
        self.assertIn("APPARENT_STATIC_ARBITRAGE_VERIFY_QUOTES", x.reasons)
        self.assertEqual(x.state, "INSUFFICIENT_EVIDENCE")

    def test_nonfinite_invalid_numbers_and_no_implicit_default_cost(self):
        from src.research.strategy_falsification_v1 import dec
        with self.assertRaises(ValueError):
            dec("NaN")
        with self.assertRaises(ValueError):
            dec("Infinity")
        self.assertEqual(len(evaluate(examples()["S03"], POLICY).reasons),0)


if __name__ == "__main__":
    unittest.main()
