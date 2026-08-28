import pytest

from src.providers.saxo import (
    QuoteQuality,
    SaxoClient,
    SaxoError,
    SaxoOptionContract,
    SaxoOptionQuote,
)


class FakeSaxoClient(
    SaxoClient
):
    def __init__(self):
        super().__init__(
            access_token="fake-token"
        )

        self.requests = []

    def _get_json(
        self,
        path,
        params=None,
    ):
        self.requests.append(
            (
                path,
                params,
            )
        )

        if (
            path
            == "/ref/v1/instruments"
        ):
            return {
                "Data": [
                    {
                        "AssetType":
                            "StockOption",

                        "Description":
                            "Apple Inc.",

                        "ExchangeId":
                            "OPRA",

                        "Identifier":
                            309,

                        "SummaryType":
                            "ContractOptionRoot",

                        "Symbol":
                            "AAPL:xcbf",
                    }
                ]
            }

        if path.endswith(
            "/contractoptionspaces/309"
        ):
            return {
                "OptionRootId":
                    309,

                "AssetType":
                    "StockOption",

                "ContractSize":
                    100.0,

                "OptionSpace": [
                    {
                        "Expiry":
                            "2027-01-15",

                        "SpecificOptions": [
                            {
                                "PutCall":
                                    "Call",

                                "StrikePrice":
                                    260.0,

                                "TradingStatus":
                                    "Tradable",

                                "Uic":
                                    44557464,

                                "UnderlyingUic":
                                    211,
                            },
                            {
                                "PutCall":
                                    "Put",

                                "StrikePrice":
                                    260.0,

                                "TradingStatus":
                                    "Tradable",

                                "Uic":
                                    44557465,

                                "UnderlyingUic":
                                    211,
                            },
                        ],
                    }
                ],
            }

        if (
            path
            == "/trade/v1/infoprices"
        ):
            asset_type = (
                params.get(
                    "AssetType"
                )
                if params
                else None
            )

            if asset_type == "Stock":
                return {
                    "AssetType":
                        "Stock",

                    "LastUpdated":
                        (
                            "2026-08-27"
                            "T21:53:00.521000Z"
                        ),

                    "PriceSource":
                        "TVIEWNASD",

                    "Uic":
                        211,

                    "Quote": {
                        "Amount":
                            0,

                        "Ask":
                            314.55,

                        "AskSize":
                            0.0,

                        "Bid":
                            314.54,

                        "BidSize":
                            0.0,

                        "DelayedByMinutes":
                            15,

                        "ErrorCode":
                            "None",

                        "MarketState":
                            "Closed",

                        "Mid":
                            314.55,

                        "PriceSource":
                            "TVIEWNASD",

                        "PriceSourceType":
                            "Indicative",

                        "PriceTypeAsk":
                            "OldIndicative",

                        "PriceTypeBid":
                            "OldIndicative",
                    },
                }

            return {
                "AssetType":
                    "StockOption",

                "LastUpdated":
                    (
                        "2026-08-27"
                        "T21:00:34.880000Z"
                    ),

                "PriceSource":
                    "OPRA",

                "Uic":
                    44557464,

                "Quote": {
                    "Amount":
                        1,

                    "Ask":
                        63.85,

                    "AskSize":
                        0.0,

                    "Bid":
                        62.2,

                    "BidSize":
                        0.0,

                    "DelayedByMinutes":
                        15,

                    "ErrorCode":
                        "None",

                    "MarketState":
                        "Closed",

                    "Mid":
                        63.025,

                    "PriceSource":
                        "OPRA",

                    "PriceSourceType":
                        "Firm",

                    "PriceTypeAsk":
                        "OldIndicative",

                    "PriceTypeBid":
                        "OldIndicative",
                },
            }

        raise AssertionError(
            "Unexpected fake request: "
            f"{path}"
        )


def make_quote(
    *,
    bid=10.0,
    ask=10.2,
    bid_size=5.0,
    ask_size=5.0,
    delayed_by_minutes=0,
    market_state="Open",
    price_source_type="Firm",
    price_type_bid="Tradable",
    price_type_ask="Tradable",
):
    return SaxoOptionQuote(
        uic=123,

        bid=bid,

        ask=ask,

        mid=(
            None
            if (
                bid is None
                or ask is None
            )
            else (
                bid + ask
            ) / 2
        ),

        bid_size=bid_size,

        ask_size=ask_size,

        delayed_by_minutes=(
            delayed_by_minutes
        ),

        market_state=market_state,

        price_source="OPRA",

        price_source_type=(
            price_source_type
        ),

        price_type_bid=(
            price_type_bid
        ),

        price_type_ask=(
            price_type_ask
        ),

        last_updated=(
            "2026-08-27T20:00:00Z"
        ),
    )


def test_find_aapl_option_root():
    client = FakeSaxoClient()

    root = (
        client.find_option_root(
            "AAPL"
        )
    )

    assert (
        root["Identifier"]
        == 309
    )

    assert (
        root["ExchangeId"]
        == "OPRA"
    )


def test_find_specific_option_contract():
    client = FakeSaxoClient()

    contract = (
        client.find_option_contract(
            underlying="AAPL",
            expiration="2027-01-15",
            strike=260,
            put_call="Call",
        )
    )

    assert contract.uic == 44557464

    assert (
        contract.option_root_id
        == 309
    )

    assert (
        contract.underlying_uic
        == 211
    )

    assert (
        contract.put_call
        == "Call"
    )

    assert contract.strike == 260

    assert (
        contract.expiration
        == "2027-01-15"
    )

    assert (
        contract.trading_status
        == "Tradable"
    )

    assert (
        contract.contract_size
        == 100.0
    )


def test_specific_date_filter_is_used():
    client = FakeSaxoClient()

    client.find_option_contract(
        underlying="AAPL",
        expiration="2027-01-15",
        strike=260,
        put_call="Call",
    )

    option_space_requests = [
        request
        for request
        in client.requests
        if (
            "contractoptionspaces"
            in request[0]
        )
    ]

    assert (
        len(
            option_space_requests
        )
        == 1
    )

    _, params = (
        option_space_requests[0]
    )

    assert (
        params[
            "OptionSpaceSegment"
        ]
        == "SpecificDates"
    )

    assert (
        params[
            "ExpiryDates"
        ]
        == "2027-01-15"
    )


def test_quote_normalization():
    client = FakeSaxoClient()

    quote = (
        client.get_option_quote(
            44557464
        )
    )

    assert (
        quote.uic
        == 44557464
    )

    assert quote.bid == 62.2
    assert quote.ask == 63.85
    assert quote.mid == 63.025

    assert (
        quote.delayed_by_minutes
        == 15
    )

    assert (
        quote.market_state
        == "Closed"
    )

    assert (
        quote.price_source
        == "OPRA"
    )

    assert (
        quote.price_type_bid
        == "OldIndicative"
    )

    assert (
        quote.price_type_ask
        == "OldIndicative"
    )


def test_quote_spread():
    client = FakeSaxoClient()

    quote = (
        client.get_option_quote(
            44557464
        )
    )

    assert (
        quote.spread
        == pytest.approx(
            1.65
        )
    )

    assert (
        quote.computed_mid
        == pytest.approx(
            (
                62.2
                + 63.85
            ) / 2
        )
    )

    assert (
        quote.spread_pct_mid
        == pytest.approx(
            1.65
            / (
                (
                    62.2
                    + 63.85
                )
                / 2
            )
        )
    )


def test_contract_and_quote():
    client = FakeSaxoClient()

    (
        contract,
        quote,
    ) = (
        client
        .get_option_contract_and_quote(
            underlying="AAPL",
            expiration="2027-01-15",
            strike=260,
            put_call="Call",
        )
    )

    assert (
        contract.uic
        == 44557464
    )

    assert (
        quote.uic
        == 44557464
    )

    assert quote.bid == 62.2
    assert quote.ask == 63.85


def test_missing_contract_raises():
    client = FakeSaxoClient()

    with pytest.raises(
        SaxoError,
        match=(
            "No Saxo option "
            "contract matched"
        ),
    ):
        client.find_option_contract(
            underlying="AAPL",
            expiration="2027-01-15",
            strike=999,
            put_call="Call",
        )


def test_missing_bid_ask_remain_none():
    class MissingQuoteClient(
        FakeSaxoClient
    ):
        def _get_json(
            self,
            path,
            params=None,
        ):
            if (
                path
                == "/trade/v1/infoprices"
            ):
                return {
                    "Uic":
                        123,

                    "PriceSource":
                        "OPRA",

                    "Quote": {
                        "PriceTypeBid":
                            "NoAccess",

                        "PriceTypeAsk":
                            "NoAccess",
                    },
                }

            return super()._get_json(
                path,
                params,
            )

    client = (
        MissingQuoteClient()
    )

    quote = (
        client.get_option_quote(
            123
        )
    )

    assert quote.bid is None
    assert quote.ask is None
    assert quote.spread is None

    assert (
        quote.spread_pct_mid
        is None
    )

    assert (
        quote.price_type_bid
        == "NoAccess"
    )

    assert (
        quote.price_type_ask
        == "NoAccess"
    )

    assert (
        quote.quality
        == QuoteQuality.UNAVAILABLE
    )

    assert (
        quote.is_executable
        is False
    )


def test_old_indicative_quote_is_stale():
    quote = make_quote(
        market_state="Closed",
        delayed_by_minutes=15,
        price_type_bid=(
            "OldIndicative"
        ),
        price_type_ask=(
            "OldIndicative"
        ),
        bid_size=0.0,
        ask_size=0.0,
    )

    assert (
        quote.quality
        == QuoteQuality.STALE
    )

    assert (
        quote.is_executable
        is False
    )


def test_closed_market_quote_is_indicative():
    quote = make_quote(
        market_state="Closed",
        delayed_by_minutes=0,
        price_type_bid="Tradable",
        price_type_ask="Tradable",
    )

    assert (
        quote.quality
        == QuoteQuality.INDICATIVE
    )

    assert (
        quote.is_executable
        is False
    )


def test_zero_size_quote_is_indicative():
    quote = make_quote(
        market_state="Open",
        bid_size=0.0,
        ask_size=0.0,
        delayed_by_minutes=0,
    )

    assert (
        quote.quality
        == QuoteQuality.INDICATIVE
    )

    assert (
        quote.is_executable
        is False
    )


def test_missing_size_quote_is_indicative():
    quote = make_quote(
        market_state="Open",
        bid_size=None,
        ask_size=5.0,
        delayed_by_minutes=0,
    )

    assert (
        quote.quality
        == QuoteQuality.INDICATIVE
    )

    assert (
        quote.is_executable
        is False
    )


def test_non_firm_quote_is_indicative():
    quote = make_quote(
        market_state="Open",
        bid_size=5.0,
        ask_size=5.0,
        delayed_by_minutes=0,
        price_source_type="Indicative",
    )

    assert (
        quote.quality
        == QuoteQuality.INDICATIVE
    )

    assert (
        quote.is_executable
        is False
    )


def test_delayed_open_quote_is_delayed():
    quote = make_quote(
        market_state="Open",
        delayed_by_minutes=15,
        bid_size=5.0,
        ask_size=5.0,
    )

    assert (
        quote.quality
        == QuoteQuality.DELAYED
    )

    assert (
        quote.is_executable
        is False
    )


def test_firm_open_fresh_quote_is_executable():
    quote = make_quote(
        market_state="Open",
        delayed_by_minutes=0,
        bid_size=5.0,
        ask_size=5.0,
        price_source_type="Firm",
        price_type_bid="Tradable",
        price_type_ask="Tradable",
    )

    assert (
        quote.quality
        == QuoteQuality.EXECUTABLE
    )

    assert (
        quote.is_executable
        is True
    )


def test_no_access_is_unavailable_even_if_prices_exist():
    quote = make_quote(
        bid=10.0,
        ask=10.2,
        price_type_bid="NoAccess",
        price_type_ask="NoAccess",
    )

    assert (
        quote.quality
        == QuoteQuality.UNAVAILABLE
    )

    assert (
        quote.is_executable
        is False
    )


def test_underlying_quote_normalization():
    client = FakeSaxoClient()

    quote = (
        client.get_underlying_quote(
            uic=211,
            asset_type="Stock",
        )
    )

    assert quote.uic == 211

    assert (
        quote.asset_type
        == "Stock"
    )

    assert quote.bid == 314.54
    assert quote.ask == 314.55

    assert quote.mid == 314.55

    assert (
        quote.computed_mid
        == pytest.approx(
            314.545
        )
    )

    assert (
        quote.reference_price
        == pytest.approx(
            314.545
        )
    )

    assert (
        quote.spread
        == pytest.approx(
            0.01
        )
    )

    assert (
        quote.price_source
        == "TVIEWNASD"
    )

    assert (
        quote.last_updated
        == (
            "2026-08-27"
            "T21:53:00.521000Z"
        )
    )


def test_live_shaped_underlying_quote_is_stale():
    client = FakeSaxoClient()

    quote = (
        client.get_underlying_quote(
            211
        )
    )

    assert (
        quote.market_state
        == "Closed"
    )

    assert (
        quote.delayed_by_minutes
        == 15
    )

    assert (
        quote.price_type_bid
        == "OldIndicative"
    )

    assert (
        quote.price_type_ask
        == "OldIndicative"
    )

    assert (
        quote.quality
        == QuoteQuality.STALE
    )

    assert (
        quote.is_executable
        is False
    )


def test_underlying_quote_uses_stock_asset_type():
    client = FakeSaxoClient()

    client.get_underlying_quote(
        211
    )

    infoprice_requests = [
        request
        for request
        in client.requests
        if (
            request[0]
            == "/trade/v1/infoprices"
        )
    ]

    path, params = (
        infoprice_requests[-1]
    )

    assert (
        path
        == "/trade/v1/infoprices"
    )

    assert (
        params["Uic"]
        == 211
    )

    assert (
        params["AssetType"]
        == "Stock"
    )

    assert (
        params["FieldGroups"]
        == "Quote"
    )


def test_option_contract_can_resolve_underlying_quote():
    client = FakeSaxoClient()

    contract = (
        client.find_option_contract(
            underlying="AAPL",
            expiration="2027-01-15",
            strike=260,
            put_call="Call",
        )
    )

    quote = (
        client
        .get_option_underlying_quote(
            contract
        )
    )

    assert (
        contract.underlying_uic
        == 211
    )

    assert quote.uic == 211

    assert (
        quote.reference_price
        == pytest.approx(
            314.545
        )
    )


def test_option_without_underlying_uic_fails_safely():
    client = FakeSaxoClient()

    contract = SaxoOptionContract(
        uic=123,
        option_root_id=309,
        underlying_uic=None,
        underlying="AAPL",
        put_call="Call",
        strike=260.0,
        expiration="2027-01-15",
        trading_status="Tradable",
        contract_size=100.0,
    )

    with pytest.raises(
        SaxoError,
        match="has no underlying UIC",
    ):
        client.get_option_underlying_quote(
            contract
        )
