import pytest

from src.providers.saxo import (
    SaxoClient,
    SaxoUnderlyingResolutionError,
)


def test_underlying_resolution_prefers_primary_listing(
    monkeypatch,
):
    client = SaxoClient(access_token="token")

    monkeypatch.setattr(
        client,
        "search_underlying_stocks",
        lambda symbol: [
            {
                "Identifier": 211,
                "PrimaryListing": 211,
                "Symbol": "AAPL:xnas",
                "ExchangeId": "NASDAQ",
                "CurrencyCode": "USD",
            },
            {
                "Identifier": 15777171,
                "PrimaryListing": 211,
                "Symbol": "AAPL:xmil",
                "ExchangeId": "MIL",
                "CurrencyCode": "EUR",
            },
        ],
    )

    result = client.find_underlying_stock("AAPL")

    assert result["Identifier"] == 211
    assert result["Symbol"] == "AAPL:xnas"


def test_underlying_resolution_rejects_multiple_primary_listings(
    monkeypatch,
):
    client = SaxoClient(access_token="token")

    monkeypatch.setattr(
        client,
        "search_underlying_stocks",
        lambda symbol: [
            {
                "Identifier": 1,
                "PrimaryListing": 1,
                "Symbol": "TEST:xone",
            },
            {
                "Identifier": 2,
                "PrimaryListing": 2,
                "Symbol": "TEST:xtwo",
            },
        ],
    )

    with pytest.raises(
        SaxoUnderlyingResolutionError
    ):
        client.find_underlying_stock("TEST")
