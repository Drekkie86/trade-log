"""Stage-0 UI preset tests: never market data or broker-authorized fixtures."""
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal

from src.research.strategy_falsification_v1 import CATALOGUE, evaluate
from src.research.shadow_stage0_scenarios_v1 import hypothetical_scenario

ANCHOR=datetime(2026,10,12,15,0,tzinfo=timezone.utc)

class Stage0PresetTests(unittest.TestCase):
    def test_every_family_is_present_and_synthetic(self):
        self.assertEqual(len(CATALOGUE),11)
        for key in CATALOGUE:
            with self.subTest(key=key):
                s,p=hypothetical_scenario(key,decision_time=ANCHOR)
                self.assertIn("SYNTHETIC",s.signal_version)
                self.assertIsNone(p.bankroll_eur)
                self.assertFalse(p.verified_share_inventory)
                self.assertTrue(all(leg.source_id=="SYNTHETIC_NOT_A_MARKET_RECORD" for leg in s.legs))
                result=evaluate(s,replace(p,bankroll_eur=Decimal("2500")))
                self.assertNotEqual(result.state,"FAILED_STRUCTURE")
                self.assertNotEqual(result.state,"UNSCORABLE")
                self.assertNotEqual(result.state,"TRADE_APPROVED")
    def test_assumed_vertical_is_only_indicative(self):
        s,p=hypothetical_scenario("S03",decision_time=ANCHOR)
        r=evaluate(s,replace(p,bankroll_eur=Decimal("700")))
        self.assertEqual(r.state,"INDICATIVELY_AFFORDABLE_NOT_EXECUTABLE")
        self.assertEqual(r.gross_max_loss_usd,"300.00")
        self.assertEqual(r.conservative_capital_eur,"285.46")
    def test_naive_clock_not_accepted(self):
        with self.assertRaises(ValueError):
            hypothetical_scenario("S03",decision_time=datetime(2026,10,12,15,0))
    def test_unknown_family_not_silently_admitted(self):
        with self.assertRaises(ValueError):
            hypothetical_scenario("S99",decision_time=ANCHOR)
    def test_bad_manually_assumed_quote_blocks(self):
        s,p=hypothetical_scenario("S03",decision_time=ANCHOR)
        l=replace(s.legs[0],ask=Decimal("4"))
        r=evaluate(replace(s,legs=(l,s.legs[1])),replace(p,bankroll_eur=Decimal("1000")))
        self.assertEqual(r.state,"UNSCORABLE")
        self.assertIn("CROSSED_OR_INVALID_QUOTE",r.reasons)
if __name__=="__main__":
    unittest.main()
