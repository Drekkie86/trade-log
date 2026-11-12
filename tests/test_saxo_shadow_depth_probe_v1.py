"""Tests are synthetic only; no actual Saxo token, account or network."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from src.providers.saxo import (
    SaxoOptionContract, SaxoOptionQuote, SaxoClient,
    SaxoContractResolutionError,
)
from src.research.saxo_shadow_depth_probe_v1 import capture_candidate_saxo_depth

NOW = datetime(2026, 10, 12, 14, 0, 0, tzinfo=timezone.utc)
LEG_DATA = [
    {"option_quote_id": 101, "right": "C", "strike": 100.0,
     "side": "BUY", "quantity": 1, "shares_per_contract": 100},
    {"option_quote_id": 102, "right": "C", "strike": 105.0,
     "side": "SELL", "quantity": 1, "shares_per_contract": 100},
]


def _db(tmp_path, *, legs=None, state="SHADOW_TRACKED", expiry="2026-11-20"):
    path = tmp_path / "saxo_probe.db"
    c = sqlite3.connect(path)
    c.executescript("""
        CREATE TABLE shadow_candidates (
            id INTEGER PRIMARY KEY, underlying TEXT,
            structure_json TEXT, research_run_id INTEGER,
            reference_contract_id INTEGER);
        CREATE TABLE listing_reference_contracts (id INTEGER PRIMARY KEY,
            expiration TEXT);
        CREATE TABLE shadow_state_events (
            id INTEGER PRIMARY KEY, candidate_id INTEGER, to_state TEXT);
        CREATE INDEX ix_state ON shadow_state_events(candidate_id,id);
    """)
    c.execute("INSERT INTO listing_reference_contracts VALUES(1,?)",(expiry,))
    c.execute("INSERT INTO shadow_candidates VALUES(12,'AAPL',?,2,1)",
              (json.dumps({"legs":LEG_DATA if legs is None else legs}),))
    c.execute("INSERT INTO shadow_state_events VALUES(1,12,?)",(state,))
    c.commit()
    c.close()
    return path


def quote_for(uic, *, at="2026-10-12T13:59:58Z",
              size=3, bid=2.5, ask=2.7, price_source_type="FIRM",
              delayed_by_minutes=0):
    return SaxoOptionQuote(
        uic=uic,bid=bid,ask=ask,mid=(bid+ask)/2,
        bid_size=size,ask_size=size,
        delayed_by_minutes=delayed_by_minutes,
        market_state="OPEN",price_source="SAXO",
        price_source_type=price_source_type,
        price_type_bid="Firm",price_type_ask="Firm",
        last_updated=at,
    )


class FakeSaxo:
    def __init__(self, *, stamp=None, size=3, mismatch=False,
                 price_source_type="FIRM", fails=False):
        self.calls=[]
        self.resolution_calls=0
        self.contracts_by_uic={}
        self.stamp=stamp or "2026-10-12T13:59:58Z"
        self.size=size
        self.mismatch=mismatch
        self.price_source_type=price_source_type
        self.fails=fails

    def find_option_contracts_batch(self, *, underlying, requests):
        self.resolution_calls+=1
        result=[]
        for expiration,strike,put_call in requests:
            uic=1000+int(strike)
            contract=SaxoOptionContract(
                uic=uic,option_root_id=5,underlying_uic=17,
                underlying=underlying,put_call=put_call,
                strike=strike,expiration=expiration,
                trading_status="Tradable",
                contract_size=10 if self.mismatch else 100)
            self.contracts_by_uic[uic]=contract
            result.append(contract)
        return result

    def get_option_quote(self, uic):
        contract=self.contracts_by_uic[uic]
        self.calls.append((contract.underlying,contract.expiration,
                           contract.strike,contract.put_call))
        if self.fails:
            raise RuntimeError("SYNTHETIC_PROVIDER_FAILURE_WITH_NO_SECRET")
        return quote_for(
            uic,at=self.stamp,size=self.size,
            price_source_type=self.price_source_type)


def sample(tmp_path, *, fake=None, at=NOW, enable=True, **data):
    p=_db(tmp_path,**data)
    c=fake or FakeSaxo()
    r=capture_candidate_saxo_depth(
        candidate_id=12,db_path=p,saxo_client=c,
        allow_provider_get=enable,clock=lambda:at)
    return r,c,p




class CountedBatchSaxo(SaxoClient):
    """No HTTP requests: model the existing Saxo root/option-space response."""
    def __init__(self):
        super().__init__(access_token="SYNTHETIC_NONSECRET")
        self.root_calls=0
        self.space_calls=[]
    def find_option_root(self, underlying):
        self.root_calls+=1
        return {"Identifier":309}
    def get_option_space(self, option_root_id, expiration=None):
        self.space_calls.append((option_root_id, expiration))
        return {
            "ContractSize":100,
            "OptionSpace":[{
                "Expiry":expiration,
                "SpecificOptions":[
                    {"Uic":1100,"StrikePrice":100,"PutCall":"Call",
                     "TradingStatus":"Tradable"},
                    {"Uic":1105,"StrikePrice":105,"PutCall":"Call",
                     "TradingStatus":"Tradable"},
                    {"Uic":1107,"StrikePrice":107,"PutCall":"Put",
                     "TradingStatus":"Tradable"},
                ]
            }],
        }


def test_batch_contract_resolver_reuses_root_and_option_space():
    c=CountedBatchSaxo()
    rows=c.find_option_contracts_batch(
        underlying="AAPL",
        requests=[("2026-11-20",100.0,"Call"),
                  ("2026-11-20",105.0,"Call"),
                  ("2026-11-20",107.0,"Put")])
    assert [x.uic for x in rows]==[1100,1105,1107]
    assert all(x.contract_size==100 for x in rows)
    assert c.root_calls==1
    assert c.space_calls==[(309,"2026-11-20")]


def test_batch_resolves_all_contracts_before_quote_calls():
    c=CountedBatchSaxo()
    with pytest.raises(SaxoContractResolutionError):
        c.find_option_contracts_batch(
            underlying="AAPL",
            requests=[("2026-11-20",100.0,"Call"),
                      ("2026-11-20",999.0,"Call")])
    assert c.root_calls==1
    assert c.space_calls==[(309,"2026-11-20")]


def test_batch_rejects_duplicate_and_unbounded_requests_without_io():
    c=CountedBatchSaxo()
    request=("2026-11-20",100.0,"Call")
    with pytest.raises(ValueError,match="DUPLICATE"):
        c.find_option_contracts_batch(underlying="AAPL",requests=[request,request])
    with pytest.raises(ValueError,match="OUT_OF_BOUNDS"):
        c.find_option_contracts_batch(underlying="AAPL",requests=[request]*5)
    assert c.root_calls==0
    assert c.space_calls==[]



def test_slow_contract_resolution_stops_before_any_price_get(tmp_path):
    p=_db(tmp_path)
    client=FakeSaxo()
    times=iter([NOW,datetime(2026,10,12,14,0,16,tzinfo=timezone.utc)])
    result=capture_candidate_saxo_depth(
        candidate_id=12,db_path=p,saxo_client=client,
        allow_provider_get=True,clock=lambda:next(times))
    assert "SAXO_SAMPLE_TIME_BUDGET_EXCEEDED" in result.reason_codes
    assert client.resolution_calls==1
    assert client.calls==[]
    assert result.outcome_eligible is False

def test_provider_disabled_is_inert_no_saxo_calls(tmp_path):
    r,client,_=sample(tmp_path,enable=False)
    assert client.calls==[]
    assert r.reason_codes==("PROVIDER_READS_NOT_AUTHORIZED",)
    assert r.legs_observed==0
    assert r.outcome_eligible is False


def test_sunday_market_closed_zero_saxo_calls(tmp_path):
    r,c,_=sample(tmp_path,at=datetime(2026,10,11,14,tzinfo=timezone.utc))
    assert r.reason_codes==("XNYS_MARKET_CLOSED",)
    assert c.calls==[]


def test_outside_exchange_market_window_does_not_call_provider(tmp_path):
    r,c,_=sample(tmp_path,at=datetime(2026,10,12,13,tzinfo=timezone.utc))
    assert r.reason_codes==("OUTSIDE_XNYS_SAMPLE_WINDOW",)
    assert c.calls==[]


def test_two_leg_bid_ask_depth_qualifies_only_as_reference(tmp_path):
    r,c,p=sample(tmp_path)
    assert len(c.calls)==2
    assert c.calls[0]==("AAPL","2026-11-20",100,"Call")
    assert r.status=="LEG_SAXO_DEPTH_OBSERVED_NOT_PACKAGE_EXECUTION"
    assert r.reason_codes==()
    assert r.legs_observed==2 and r.legs_requested==2
    assert len({x.option_quote_id for x in r.leg_evidence})==2
    assert len(r.evidence_sha256)==64
    assert r.as_dict()["outcome_eligible"] is False
    assert r.independent_package_execution_verified is False
    assert r.trading_enabled is False
    assert r.observation_only is True
    # open read only: source SQLite has no inserted evidence tables
    with sqlite3.connect(p) as db:
        assert db.execute("SELECT COUNT(*) FROM shadow_candidates").fetchone()[0]==1
        assert db.execute("SELECT COUNT(*) FROM shadow_state_events").fetchone()[0]==1


def test_stale_quote_fails_first_leg_without_more_calls(tmp_path):
    r,c,_=sample(tmp_path,fake=FakeSaxo(stamp="2026-10-12T13:59:20Z"))
    assert "SAXO_QUOTE_SOURCE_TIMESTAMP_STALE_OR_FUTURE" in r.reason_codes
    assert "SAXO_LEG_POPULATION_INCOMPLETE" in r.reason_codes
    assert len(c.calls)==1
    assert not r.outcome_eligible


def test_provider_weak_quality_does_not_masquerade_as_execution(tmp_path):
    r,c,_=sample(tmp_path,fake=FakeSaxo(price_source_type="INDICATIVE"))
    assert "SAXO_QUOTE_NOT_EXECUTABLE_QUALITY" in r.reason_codes
    assert len(c.calls)==1


def test_insufficient_depth_fails_closed(tmp_path):
    r,c,_=sample(tmp_path,fake=FakeSaxo(size=0))
    assert "SAXO_BID_ASK_OR_DEPTH_INSUFFICIENT" in r.reason_codes
    assert len(c.calls)==1


def test_mismatched_contract_multiplier_fails_closed(tmp_path):
    r,c,_=sample(tmp_path,fake=FakeSaxo(mismatch=True))
    assert "SAXO_CONTRACT_OR_ACQUISITION_IDENTITY_INVALID" in r.reason_codes
    assert len(c.calls)==1


def test_provider_failure_redacts_exception_details(tmp_path):
    r,c,_=sample(tmp_path,fake=FakeSaxo(fails=True))
    assert "SAXO_PROVIDER_READ_OR_RESOLUTION_FAILED" in r.reason_codes
    assert "NO_SECRET" not in str(r.as_dict())


def test_inactive_candidate_never_calls_saxo(tmp_path):
    r,c,_=sample(tmp_path,state="CLOSED_OR_EXPIRED")
    assert r.reason_codes==("CANDIDATE_NOT_ACTIVE_SHADOW_TRACKED",)
    assert c.calls==[]


def test_expired_option_cannot_be_reobserved(tmp_path):
    r,c,_=sample(tmp_path,expiry="2026-10-09")
    assert "CONTRACT_ALREADY_EXPIRED" in r.reason_codes
    assert c.calls==[]


def test_unrealistic_reused_quote_id_does_not_reach_provider(tmp_path):
    legs=[LEG_DATA[0],{**LEG_DATA[1],"option_quote_id":101}]
    r,c,_=sample(tmp_path,legs=legs)
    assert "FROZEN_CANDIDATE_LEG_INVALID_OR_DUPLICATE" in r.reason_codes
    assert c.calls==[]


def test_oversized_structure_prevents_unbounded_saxo_calls(tmp_path):
    legs=[{**LEG_DATA[0],"option_quote_id":i,"strike":float(80+i)}
          for i in range(1,7)]
    r,c,_=sample(tmp_path,legs=legs)
    assert r.reason_codes==("CANDIDATE_LEG_COUNT_UNSUPPORTED",)
    assert c.calls==[]


def test_invalid_id_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="INVALID_CANDIDATE_ID"):
        capture_candidate_saxo_depth(
            candidate_id=0,db_path=_db(tmp_path),saxo_client=FakeSaxo(),
            allow_provider_get=True,clock=lambda:NOW,
        )




def test_invalid_provider_option_right_is_not_silently_treated_as_put(tmp_path):
    class MalformedRight(FakeSaxo):
        def find_option_contracts_batch(self, **kwargs):
            result=super().find_option_contracts_batch(**kwargs)
            return [replace(result[0],put_call="INVALID"),*result[1:]]
    r,c,_=sample(tmp_path,fake=MalformedRight())
    assert "SAXO_CONTRACT_OR_ACQUISITION_IDENTITY_INVALID" in r.reason_codes
    assert len(c.calls)==1


def test_future_provider_timestamp_is_rejected(tmp_path):
    r,c,_=sample(tmp_path,fake=FakeSaxo(stamp="2026-10-12T14:00:10Z"))
    assert "SAXO_QUOTE_SOURCE_TIMESTAMP_STALE_OR_FUTURE" in r.reason_codes
    assert not r.outcome_eligible


def test_unverified_provider_timestamp_timezone_is_rejected(tmp_path):
    r,c,_=sample(tmp_path,fake=FakeSaxo(stamp="2026-10-12T14:00:00"))
    assert "SAXO_PROVIDER_RESPONSE_UNVERIFIABLE" in r.reason_codes
    assert not r.outcome_eligible


def test_provider_cannot_be_called_for_missing_database(tmp_path):
    client=FakeSaxo()
    with pytest.raises(ValueError, match="READ_ONLY_DATABASE_NOT_FOUND"):
        capture_candidate_saxo_depth(
            candidate_id=12,
            db_path=tmp_path/"never_created.db",
            saxo_client=client,allow_provider_get=True,
            clock=lambda:NOW)
    assert client.calls==[]

def test_missing_saxo_market_evidence_does_not_make_a_paper_fill(tmp_path):
    r,c,_=sample(tmp_path)
    assert r.legs_observed==2
    assert not r.independent_package_execution_verified
    assert not r.outcome_eligible
    assert not r.trading_enabled
