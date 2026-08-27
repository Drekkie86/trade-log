import pytest

from src.providers.saxo import (
    SaxoClient,
    SaxoError,
)


class FakeSaxoClient(SaxoClient):
    def __init__(self):
        super().__init__(access_token="fake-token")
        self.requests = []

    def _get_json(self, path, params=None):
        self.requests.append((path, params))

        if path == "/ref/v1/instruments":
            return {
                "Data": [
                    {
                        "AssetType": "StockOption",
                        "Description": "Apple Inc.",
                        "ExchangeId": "OPRA",
                        "Identifier": 309,
                        "SummaryType": "ContractOptionRoot",
                        "Symbol": "AAPL:xcbf",
                    }
                ]
            }

        if path.endswith(
            "/contractoptionspaces/309"
        ):
            return {
                "OptionRootId": 309,
                "AssetType": "StockOption",
                "OptionSpace": [
                    {
                        "Expiry": "2027-01-15",
                        "SpecificOptions": [
                            {
                                "PutCall": "Call",
                                "StrikePrice": 260.0,
                                "TradingStatus": "Tradable",
                                "Uic": 44557464,
                                "UnderlyingUic": 211,
                            },
                            {
                                "PutCall": "Put",
                                "StrikePrice": 260.0,
                                "TradingStatus": "Tradable",
                                "Uic": 44557465,
                                "UnderlyingUic": 211,
                            },
                        ],
                    }
                ],
            }

        if path == "/trade/v1/infoprices":
            return {
                "AssetType": "StockOption",
                "LastUpdated":
                    "2026-08-27T21:00:34.880000Z",
                "PriceSource": "OPRA",
                "Uic": 44557464,
                "Quote": {
                    "Amount": 1,
                    "Ask": 63.85,
                    "AskSize": 0.0,
                    "Bid": 62.2,
                    "BidSize": 0.0,
                    "DelayedByMinutes": 15,
                    "ErrorCode": "None",
                    "MarketState": "Closed",
                    "Mid": 63.025,
                    "PriceSource": "OPRA",
                    "PriceSourceType": "Firm",
                    "PriceTypeAsk": "OldIndicative",
                    "PriceTypeBid": "OldIndicative",
                },
            }

        raise AssertionError(
            f"Unexpected fake request: {path}"
        )


def test_find_aapl_option_root():
    client = FakeSaxoClient()

    root = client.find_option_root("AAPL")

    assert root["Identifier"] == 309
    assert root["ExchangeId"] == "OPRA"


def test_find_specific_option_contract():
    client = FakeSaxoClient()

    contract = client.find_option_contract(
        underlying="AAPL",
        expiration="2027-01-15",
        strike=260,
        put_call="Call",
    )

    assert contract.uic == 44557464
    assert contract.option_root_id == 309
    assert contract.underlying_uic == 211
    assert contract.put_call == "Call"
    assert contract.strike == 260
    assert contract.expiration == "2027-01-15"
    assert contract.trading_status == "Tradable"


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
        for request in client.requests
        if "contractoptionspaces" in request[0]
    ]

    assert len(option_space_requests) == 1

    _, params = option_space_requests[0]

    assert params["OptionSpaceSegment"] == (
        "SpecificDates"
    )
    assert params["ExpiryDates"] == "2027-01-15"


def test_quote_normalization():
    client = FakeSaxoClient()

    quote = client.get_option_quote(44557464)

    assert quote.uic == 44557464
    assert quote.bid == 62.2
    assert quote.ask == 63.85
    assert quote.mid == 63.025
    assert quote.delayed_by_minutes == 15
    assert quote.market_state == "Closed"
    assert quote.price_source == "OPRA"
    assert quote.price_type_bid == "OldIndicative"
    assert quote.price_type_ask == "OldIndicative"


def test_quote_spread():
    client = FakeSaxoClient()

    quote = client.get_option_quote(44557464)

    assert quote.spread == pytest.approx(1.65)

    assert quote.spread_pct_mid == pytest.approx(
        1.65 / 63.025
    )


def test_contract_and_quote():
    client = FakeSaxoClient()

    contract, quote = (
        client.get_option_contract_and_quote(
            underlying="AAPL",
            expiration="2027-01-15",
            strike=260,
            put_call="Call",
        )
    )

    assert contract.uic == 44557464
    assert quote.uic == 44557464
    assert quote.bid == 62.2
    assert quote.ask == 63.85


def test_missing_contract_raises():
    client = FakeSaxoClient()

    with pytest.raises(
        SaxoError,
        match="No Saxo option contract matched",
    ):
        client.find_option_contract(
            underlying="AAPL",
            expiration="2027-01-15",
            strike=999,
            put_call="Call",
        )


def test_missing_bid_ask_remain_none():
    class MissingQuoteClient(FakeSaxoClient):
        def _get_json(self, path, params=None):
            if path == "/trade/v1/infoprices":
                return {
                    "Uic": 123,
                    "PriceSource": "OPRA",
                    "Quote": {
                        "PriceTypeBid": "NoAccess",
                        "PriceTypeAsk": "NoAccess",
                    },
                }

            return super()._get_json(path, params)

    client = MissingQuoteClient()

    quote = client.get_option_quote(123)

    assert quote.bid is None
    assert quote.ask is None
    assert quote.spread is None
    assert quote.spread_pct_mid is None
    assert quote.price_type_bid == "NoAccess"
    assert quote.price_type_ask == "NoAccess"