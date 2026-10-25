"""Strict source qualification for a small, read-only Saxo LIVE price probe."""
from dataclasses import replace
from datetime import UTC, datetime, timedelta
import pytest
from src.providers.saxo import SaxoOptionQuote, SaxoUnderlyingQuote
from src.operations.saxo_live_quote_evidence_v1 import (
    qualify_quote, probe_saxo_spot_opra, _expiries,
)

CUT=datetime(2026,10,26,15,0,tzinfo=UTC)  # 11:00 in New York, weekday


def stock(**kwargs):
    fields=dict(
        uic=211,asset_type="Stock",bid=199.96,ask=200.02,
        mid=199.99,bid_size=150,ask_size=170,
        delayed_by_minutes=0,market_state="Open",
        price_source="SAXO",price_source_type="FIRM",
        price_type_bid="Tradable",price_type_ask="Tradable",
        last_updated=(CUT-timedelta(seconds=4)).isoformat(),
    )
    fields.update(kwargs)
    return SaxoUnderlyingQuote(**fields)


def option(**kwargs):
    fields=dict(
        uic=991,bid=2.45,ask=2.55,mid=2.50,
        bid_size=20,ask_size=25,delayed_by_minutes=0,
        market_state="Open",price_source="SAXO",
        price_source_type="FIRM",price_type_bid="Tradable",
        price_type_ask="Tradable",
        last_updated=(CUT-timedelta(seconds=3)).isoformat(),
    )
    fields.update(kwargs)
    return SaxoOptionQuote(**fields)


def test_unambiguous_live_firm_sample_is_still_not_an_order_price():
    a=qualify_quote(stock(),now=CUT)
    b=qualify_quote(option(),now=CUT)
    assert a.state=="REALTIME_FIRM_REFERENCE"
    assert b.state=="REALTIME_FIRM_REFERENCE"


@pytest.mark.parametrize("kwargs,verdict",[
    ({"delayed_by_minutes":15},"DELAYED"),
    ({"delayed_by_minutes":None},"DELAY_UNKNOWN"),
    ({"price_type_bid":"NoAccess"},"NO_ACCESS"),
    ({"error_code":"NoAccess"},"NO_ACCESS"),
    ({"error_code":"NoMarket"},"NO_MARKET_QUOTE"),
    ({"error_code":"Pending"},"NO_MARKET_QUOTE"),
    ({"error_code":"SomeOtherError"},"PROVIDER_PRICE_ERROR"),
    ({"price_type_ask":"OldIndicative"},"OLD_INDICATIVE"),
    ({"market_state":"Closed"},"SESSION_CLOSED_OR_UNKNOWN"),
    ({"market_state":None},"SESSION_CLOSED_OR_UNKNOWN"),
    ({"last_updated":"0001-01-01T00:00:00Z"},"STALE"),
    ({"last_updated":None},"CLOCK_UNKNOWN"),
    ({"last_updated":(CUT-timedelta(seconds=70)).isoformat()},"STALE"),
    ({"last_updated":(CUT+timedelta(seconds=5)).isoformat()},"STALE"),
    ({"bid":3.4,"ask":2.5},"NO_TWO_SIDED_DEPTH"),
    ({"bid_size":None},"NO_TWO_SIDED_DEPTH"),
    ({"price_type_bid":"Indicative"},"REALTIME_INDICATIVE"),
    ({"price_source_type":None},"REALTIME_SOURCE_UNCONFIRMED"),
])
def test_strict_source_rejects_nonqualifying_option(kwargs,verdict):
    assert qualify_quote(option(**kwargs),now=CUT).state==verdict


def test_sunday_never_confirms_live_feed_or_makes_paid_requests():
    sunday=datetime(2026,10,25,15,tzinfo=UTC)
    never=lambda **kwargs: (_ for _ in ()).throw(AssertionError("provider requested"))
    result=probe_saxo_spot_opra(now=sunday,client_factory=never)
    assert result.state=="MARKET_CLOSED_UNVERIFIED"
    assert result.stock is None and result.option is None
    assert result.order_authority is False
    assert result.broker_fill_verified is False


class Fake:
    calls=[]
    def __init__(self,**kwargs):
        assert kwargs["base_url"].endswith("/openapi")
        assert kwargs["timeout_seconds"] <= 8
    def find_option_root(self,symbol):
        self.calls.append(("root",symbol))
        return {"Identifier":309,"ExchangeId":"OPRA"}
    def get_option_space(self,identifier,expiration=None):
        self.calls.append(("space",identifier,expiration))
        return {
            "ContractSize":100,
            "OptionSpace":[{
                "Expiry":expiration,
                "SpecificOptions":[{
                    "PutCall":"Call","Uic":991,"UnderlyingUic":211,
                    "StrikePrice":200,
                },{
                    "PutCall":"Put","Uic":992,"UnderlyingUic":211,
                    "StrikePrice":200,
                },{
                    "PutCall":"Call","Uic":993,"UnderlyingUic":211,
                    "StrikePrice":210,
                }],
            }],
        }
    def get_underlying_quote(self,uic):
        self.calls.append(("stock",uic))
        return stock()
    def get_option_quote(self,uic):
        self.calls.append(("option",uic))
        return option()


def test_one_bounded_expiry_source_scan_frozen_no_execution_authority():
    Fake.calls=[]
    result=probe_saxo_spot_opra(now=CUT,client_factory=Fake)
    assert result.state=="LIVE_TWO_SIDED_REFERENCE"
    assert result.symbol=="AAPL"
    assert result.stock.state=="REALTIME_FIRM_REFERENCE"
    assert result.option.state=="REALTIME_FIRM_REFERENCE"
    assert result.option_contract_size==100
    assert result.sampled_expiry=="2026-11-20"
    assert result.order_authority is False
    assert result.broker_fill_verified is False
    assert Fake.calls==[
        ("root","AAPL"),
        ("space",309,"2026-11-20"),
        ("stock",211),
        ("option",991),
    ]
    assert "token" not in str(result.as_dict()).lower()


@pytest.mark.parametrize("stock_quality,option_quality",[
    ({"delayed_by_minutes":15},{}),
    ({},{"price_type_ask":"NoAccess"}),
    ({},{"price_type_ask":"Indicative"}),
])
def test_mixed_quality_fails_full_gate(stock_quality,option_quality):
    class Partial(Fake):
        def get_underlying_quote(self,uic):
            return stock(**stock_quality)
        def get_option_quote(self,uic):
            return option(**option_quality)
    result=probe_saxo_spot_opra(now=CUT,client_factory=Partial)
    assert result.state=="PARTIAL_OR_UNVERIFIED"
    assert not result.order_authority


def test_absent_source_expiry_fails_closed():
    class Missing(Fake):
        def get_option_space(self,identifier,expiration=None):
            return {"OptionSpace":[]}
    result=probe_saxo_spot_opra(now=CUT,client_factory=Missing)
    assert result.state=="NO_LISTED_SAMPLE"
    assert result.stock is None


def test_predeclared_calendar_does_not_depend_on_future_price():
    assert _expiries(CUT)==("2026-11-20","2026-12-18")
    with pytest.raises(ValueError,match="TIMEZONE"):
        probe_saxo_spot_opra(now=CUT.replace(tzinfo=None))
    with pytest.raises(ValueError,match="SYMBOL"):
        probe_saxo_spot_opra(now=CUT,symbol="../../accounts")



def test_provider_exposes_quote_level_error_code_to_gate():
    from src.providers.saxo import SaxoClient

    class NoAccess(SaxoClient):
        def __init__(self):
            super().__init__(access_token="fake-not-live")
        def _get_json(self, path, params=None):
            assert path=="/trade/v1/infoprices"
            return {
                "Uic": params["Uic"], "AssetType":params["AssetType"],
                "LastUpdated":CUT.isoformat(),
                "Quote":{
                    "Bid":1.2,"Ask":1.3,"BidSize":10,"AskSize":10,
                    "DelayedByMinutes":0,"MarketState":"Open",
                    "PriceTypeBid":"Tradable","PriceTypeAsk":"Tradable",
                    "PriceSourceType":"FIRM","ErrorCode":"NoAccess",
                },
            }
    fake=NoAccess()
    option_quote=fake.get_option_quote(991)
    stock_quote=fake.get_underlying_quote(211)
    assert option_quote.error_code=="NoAccess"
    assert stock_quote.error_code=="NoAccess"
    assert qualify_quote(option_quote,now=CUT).state=="NO_ACCESS"
    assert qualify_quote(stock_quote,now=CUT).state=="NO_ACCESS"
