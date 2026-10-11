"""Synthetic Saxo native multi-leg price-only tests. No network/orders."""
from __future__ import annotations

from datetime import datetime,timezone

from src.providers.saxo import SAXO_SIM_BASE_URL,SAXO_LIVE_BASE_URL
from src.research.saxo_native_multileg_price_v1 import (
    NativePriceLeg,observe_multileg_strategy_price,PRICE_ONLY_ROUTE,
)

NOW=datetime(2026,10,12,14,0,0,tzinfo=timezone.utc)
ACCOUNT="SYNTHETIC_ACCOUNT_NEVER_LOG"


class FakeClient:
    def __init__(self,base=SAXO_SIM_BASE_URL):
        self.base_url=base
        self.auth_calls=0
    def _current_access_token(self):
        self.auth_calls+=1
        return "SYNTHETIC_TOKEN_NEVER_LOG"


def sample_response(**changes):
    result={
        "LastUpdated":"2026-10-12T13:59:58Z",
        "InstrumentPriceDetails":{"IsMarketOpen":True,"ShortTradeDisabled":False},
        "Legs":[
            {"Uic":1001,"Amount":1.0,"BuySell":"Buy","AssetType":"StockOption"},
            {"Uic":1002,"Amount":1.0,"BuySell":"Sell","AssetType":"StockOption"},
        ],
        "PriceSource":"OPRA",
        "Quote":{
            "Bid":-1.8,"Ask":-1.5, # signed credit spread is allowed
            "BidSize":2,"AskSize":2,
            "PriceSource":"OPRA","PriceSourceType":"Firm",
            "PriceTypeAsk":"Tradable","PriceTypeBid":"Tradable",
            "DelayedByMinutes":0,"ErrorCode":"None",
        },
    }
    result.update(changes)
    return result


def legs():
    return (
        NativePriceLeg(1001,1,"BUY"),
        NativePriceLeg(1002,1,"SELL"),
    )


class CapturedTransport:
    def __init__(self,response=None,fail=False):
        self.invocations=[]
        self.response=response or sample_response()
        self.fail=fail
    def __call__(self,url,body,token,timeout):
        self.invocations.append((url,body,token,timeout))
        if self.fail:
            raise RuntimeError("SYNTHETIC_TRANSPORT_SECRET_SHOULD_BE_REDACTED")
        return self.response


def run(*,client=None,transport=None,when=NOW,allow=True,options=None,
        key=ACCOUNT):
    c=client or FakeClient()
    t=transport or CapturedTransport()
    output=observe_multileg_strategy_price(
        account_key=key,legs=legs() if options is None else options,
        saxo_client=c,allow_price_only_post=allow,
        clock=lambda:when,transport=t)
    return output,c,t


def test_post_is_explicit_price_only_never_orders():
    r,c,t=run()
    assert r.status=="BROKER_PACKAGE_PRICE_REFERENCE_ONLY"
    assert r.strategy_bid==-1.8 and r.strategy_ask==-1.5
    assert r.strategy_bid_size==2 and r.strategy_ask_size==2
    assert r.reasons==()
    assert r.quoted_legs==2
    assert r.quote_age_seconds==2.0
    assert r.price_only is True
    assert not r.broker_package_fill_verified
    assert not r.outcome_eligible
    assert not r.trading_enabled
    assert len(t.invocations)==1
    url,body,token,timeout=t.invocations[0]
    assert url==SAXO_SIM_BASE_URL+PRICE_ONLY_ROUTE
    assert "orders" not in url
    assert body["FieldGroups"]==["Quote","InstrumentPriceDetails"]
    assert [x["BuySell"] for x in body["Legs"]]==["Buy","Sell"]
    assert [x["Uic"] for x in body["Legs"]]==[1001,1002]
    assert timeout<=8
    assert len(r.evidence_sha256)==64
    assert ACCOUNT not in str(r.as_dict())
    assert token not in str(r.as_dict())


def test_no_authorization_default_is_completely_inert():
    r,c,t=run(allow=False)
    assert "NATIVE_PACKAGE_PRICING_NOT_AUTHORIZED" in r.reasons
    assert c.auth_calls==0
    assert t.invocations==[]


def test_market_closed_is_not_posted():
    r,c,t=run(when=datetime(2026,10,11,14,tzinfo=timezone.utc))
    assert "XNYS_MARKET_CLOSED" in r.reasons
    assert t.invocations==[]
    assert c.auth_calls==0


def test_base_url_allowlist_never_allows_order_or_other_host():
    c=FakeClient(base="https://evil.example/openapi")
    r,c,t=run(client=c)
    assert "BROKER_ENDPOINT_NOT_ALLOWLISTED" in r.reasons
    assert c.auth_calls==0 and not t.invocations


def test_missing_strategy_size_has_unverified_depth():
    resp=sample_response()
    del resp["Quote"]["BidSize"]
    r,c,t=run(transport=CapturedTransport(resp))
    assert "PACKAGE_SIZE_OR_DEPTH_NOT_PROVEN" in r.reasons
    assert not r.outcome_eligible


def test_delayed_broker_package_quote_is_not_firm():
    resp=sample_response()
    resp["Quote"]["DelayedByMinutes"]=15
    resp["Quote"]["PriceTypeAsk"]="OldIndicative"
    r,c,t=run(transport=CapturedTransport(resp))
    assert "PACKAGE_QUOTE_NOT_FIRM_OR_NOT_REALTIME" in r.reasons
    assert r.status=="UNVERIFIED_OR_UNAVAILABLE_PACKAGE_PRICE"


def test_later_or_earlier_provider_update_fails():
    resp=sample_response(LastUpdated="2026-10-12T14:00:01Z")
    r,c,t=run(transport=CapturedTransport(resp))
    assert "PACKAGE_QUOTE_STALE_OR_FUTURE" in r.reasons
    resp=sample_response(LastUpdated="2026-10-12T13:58:00Z")
    r,c,t=run(transport=CapturedTransport(resp))
    assert "PACKAGE_QUOTE_STALE_OR_FUTURE" in r.reasons


def test_unauthenticated_or_unrecognized_account_is_not_faked():
    r,c,t=run(key="")
    assert "BROKER_ACCOUNT_IDENTITY_MISSING" in r.reasons
    assert not t.invocations


def test_mismatched_or_duplicated_leg_response_is_not_accepted():
    resp=sample_response()
    resp["Legs"][1]["Uic"]=1001
    r,c,t=run(transport=CapturedTransport(resp))
    assert "PACKAGE_LEG_IDENTITY_OR_QUANTITY_MISMATCH" in r.reasons
    assert "DUPLICATE_PACKAGE_LEG_UIC" in r.reasons


def test_outside_session_and_closed_market_response():
    r,c,t=run(when=datetime(2026,10,12,13,tzinfo=timezone.utc))
    assert "OUTSIDE_XNYS_SAMPLE_WINDOW" in r.reasons
    resp=sample_response(InstrumentPriceDetails={
        "IsMarketOpen":False,"ShortTradeDisabled":False})
    r,c,t=run(transport=CapturedTransport(resp))
    assert "PACKAGE_MARKET_CLOSED_OR_SHORT_DISABLED" in r.reasons


def test_provider_error_never_leaks_secrets():
    r,c,t=run(transport=CapturedTransport(fail=True))
    assert "BROKER_PRICE_ONLY_REQUEST_FAILED" in r.reasons
    assert "SECRET" not in str(r.as_dict())
    assert ACCOUNT not in str(r.as_dict())


def test_duplicate_input_legs_not_posted():
    r,c,t=run(options=(NativePriceLeg(1001,1,"BUY"),
                       NativePriceLeg(1001,1,"SELL")))
    assert "NATIVE_PACKAGE_LEG_IDENTITY_INVALID" in r.reasons
    assert c.auth_calls==0
    assert t.invocations==[]


def test_even_good_native_quote_is_never_a_fill_or_trade_outcome():
    r,c,t=run()
    assert r.status=="BROKER_PACKAGE_PRICE_REFERENCE_ONLY"
    assert r.broker_package_fill_verified is False
    assert r.outcome_eligible is False
    assert r.trading_enabled is False
