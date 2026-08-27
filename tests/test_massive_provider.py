import pytest

from src.providers.massive import (
    MassiveClient,
    normalize_massive_option_chain,
)


def make_payload():
    return {
        "request_id": "massive-test-request-001",
        "results": [
            {
                "details": {
                    "ticker":
                        "O:AAPL260918C00230000",

                    "contract_type":
                        "call",

                    "strike_price":
                        230.0,

                    "expiration_date":
                        "2026-09-18",
                },

                "underlying_asset": {
                    "price":
                        225.50,

                    "last_updated":
                        1787774400000000000,
                },

                "last_quote": {
                    "bid":
                        4.10,

                    "ask":
                        4.30,

                    "last_updated":
                        1787774400000000000,
                },

                "last_trade": {
                    "price":
                        4.20,

                    "sip_timestamp":
                        1787774340000000000,
                },

                "implied_volatility":
                    0.31,

                "greeks": {
                    "delta":
                        0.42,

                    "gamma":
                        0.025,

                    "theta":
                        -0.08,

                    "vega":
                        0.14,
                },

                "day": {
                    "volume":
                        1200,
                },

                "open_interest":
                    5400,
            }
        ],
    }


def test_normalize_massive_option_chain():
    snapshot, quotes = (
        normalize_massive_option_chain(
            "aapl",
            make_payload(),
        )
    )

    assert snapshot["underlying"] == "AAPL"

    assert snapshot["provider"] == "MASSIVE"

    assert (
        snapshot["provider_snapshot_id"]
        == "massive-test-request-001"
    )

    assert (
        snapshot["underlying_price"]
        == 225.50
    )

    assert (
        snapshot["underlying_source"]
        == "FETCHED"
    )

    assert snapshot["fx_to_eur"] is None

    assert snapshot["fx_source"] == "UNKNOWN"

    assert len(quotes) == 1

    quote = quotes[0]

    assert (
        quote["option_symbol"]
        == "O:AAPL260918C00230000"
    )

    assert quote["right"] == "C"

    assert quote["strike"] == 230.0

    assert (
        quote["expiration"]
        == "2026-09-18"
    )

    assert quote["bid"] == 4.10
    assert quote["ask"] == 4.30
    assert quote["last"] == 4.20

    assert (
        quote["implied_volatility"]
        == 0.31
    )

    assert quote["delta"] == 0.42
    assert quote["gamma"] == 0.025
    assert quote["theta"] == -0.08
    assert quote["vega"] == 0.14

    assert quote["volume"] == 1200

    assert (
        quote["open_interest"]
        == 5400
    )


def test_missing_greeks_are_unknown_not_zero():
    payload = make_payload()

    payload["results"][0]["greeks"] = {}

    snapshot, quotes = (
        normalize_massive_option_chain(
            "AAPL",
            payload,
        )
    )

    assert snapshot is not None

    quote = quotes[0]

    assert quote["delta"] is None
    assert quote["delta_source"] == "UNKNOWN"

    assert quote["gamma"] is None
    assert quote["gamma_source"] == "UNKNOWN"

    assert quote["theta"] is None
    assert quote["theta_source"] == "UNKNOWN"

    assert quote["vega"] is None
    assert quote["vega_source"] == "UNKNOWN"


def test_real_zero_delta_is_fetched_not_unknown():
    payload = make_payload()

    payload["results"][0][
        "greeks"
    ]["delta"] = 0.0

    _, quotes = normalize_massive_option_chain(
        "AAPL",
        payload,
    )

    quote = quotes[0]

    assert quote["delta"] == 0.0

    assert (
        quote["delta_source"]
        == "FETCHED"
    )


def test_put_contract_is_normalized():
    payload = make_payload()

    details = payload["results"][0]["details"]

    details["ticker"] = (
        "O:AAPL260918P00220000"
    )

    details["contract_type"] = "put"

    details["strike_price"] = 220.0

    _, quotes = normalize_massive_option_chain(
        "AAPL",
        payload,
    )

    assert len(quotes) == 1

    assert quotes[0]["right"] == "P"

    assert quotes[0]["strike"] == 220.0


def test_invalid_or_incomplete_contract_is_skipped():
    payload = make_payload()

    payload["results"].append(
        {
            "details": {
                "ticker":
                    "BROKEN-CONTRACT",

                "contract_type":
                    "something_else",

                "strike_price":
                    100.0,

                "expiration_date":
                    "2026-09-18",
            }
        }
    )

    payload["results"].append(
        {
            "details": {
                "ticker":
                    "MISSING-STRIKE",

                "contract_type":
                    "call",

                "expiration_date":
                    "2026-09-18",
            }
        }
    )

    _, quotes = normalize_massive_option_chain(
        "AAPL",
        payload,
    )

    assert len(quotes) == 1

    assert (
        quotes[0]["option_symbol"]
        == "O:AAPL260918C00230000"
    )


def test_massive_client_rejects_bad_requests():
    client = MassiveClient(
        api_key="test-key"
    )

    with pytest.raises(
        ValueError,
        match="Underlying cannot be blank",
    ):
        client.get_option_chain_page(
            "   "
        )

    with pytest.raises(
        ValueError,
        match="between 1 and 250",
    ):
        client.get_option_chain_page(
            "AAPL",
            limit=0,
        )

    with pytest.raises(
        ValueError,
        match="between 1 and 250",
    ):
        client.get_option_chain_page(
            "AAPL",
            limit=251,
        )