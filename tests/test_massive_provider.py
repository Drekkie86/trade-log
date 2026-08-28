from datetime import date
from urllib.error import HTTPError

import pytest

from src.providers.massive import (
    MassiveAuthenticationError,
    MassiveClient,
    MassiveTruncatedError,
    MassiveUnsafeUrlError,
    PROVENANCE_FETCHED,
    PROVENANCE_UNKNOWN,
    normalize_massive_option_chain,
)


def make_call_contract():
    return {
        "details": {
            "ticker":
                "O:AAPL270115C00260000",
            "contract_type":
                "call",
            "strike_price":
                260,
            "expiration_date":
                "2027-01-15",
            "shares_per_contract":
                100,
        },
        "underlying_asset": {
            "ticker":
                "AAPL",
            "price":
                300.0,
            "last_updated":
                1787860000000000000,
        },
        "last_quote": {
            "bid":
                62.20,
            "ask":
                63.85,
            "last_updated":
                1787860000000000000,
        },
        "last_trade": {
            "price":
                63.00,
            "sip_timestamp":
                1787860000000000000,
        },
        "greeks": {
            "delta":
                0.55,
            "gamma":
                0.02,
            "theta":
                -0.10,
            "vega":
                0.25,
        },
        "implied_volatility":
            0.35,
        "day": {
            "volume":
                123,
        },
        "open_interest":
            456,
    }


def make_payload(*results):
    return {
        "request_id":
            "request-1",
        "request_ids": [
            "request-1",
        ],
        "status":
            "OK",
        "pages_fetched":
            1,
        "truncated":
            False,
        "results":
            list(results),
    }


def test_normalize_massive_option_chain():
    payload = make_payload(
        make_call_contract()
    )

    snapshot, quotes = (
        normalize_massive_option_chain(
            "aapl",
            payload,
        )
    )

    assert snapshot["provider"] == "MASSIVE"
    assert snapshot["underlying"] == "AAPL"

    assert (
        snapshot["provider_snapshot_id"]
        == "request-1"
    )

    assert snapshot["underlying_price"] == 300.0

    assert (
        snapshot["underlying_source"]
        == PROVENANCE_FETCHED
    )

    assert len(quotes) == 1

    quote = quotes[0]

    assert (
        quote["provider_contract_id"]
        == "O:AAPL270115C00260000"
    )

    assert (
        quote["option_symbol"]
        == "O:AAPL270115C00260000"
    )

    assert quote["right"] == "C"
    assert quote["strike"] == 260

    assert (
        quote["expiration"]
        == "2027-01-15"
    )

    assert (
        quote["shares_per_contract"]
        == 100
    )

    assert quote["bid"] == 62.20
    assert quote["ask"] == 63.85
    assert quote["last"] == 63.00

    assert (
        quote["bid_source"]
        == PROVENANCE_FETCHED
    )

    assert (
        quote["ask_source"]
        == PROVENANCE_FETCHED
    )

    assert (
        quote["last_source"]
        == PROVENANCE_FETCHED
    )

    assert (
        quote["implied_volatility"]
        == 0.35
    )

    assert quote["delta"] == 0.55
    assert quote["gamma"] == 0.02
    assert quote["theta"] == -0.10
    assert quote["vega"] == 0.25

    assert quote["volume"] == 123

    assert (
        quote["open_interest"]
        == 456
    )


def test_model_fields_do_not_inherit_quote_timestamp():
    payload = make_payload(
        make_call_contract()
    )

    _, quotes = (
        normalize_massive_option_chain(
            "AAPL",
            payload,
        )
    )

    quote = quotes[0]

    assert quote["quote_at"] is not None

    assert quote["iv_at"] is None
    assert quote["delta_at"] is None
    assert quote["gamma_at"] is None
    assert quote["theta_at"] is None
    assert quote["vega_at"] is None


def test_volume_and_oi_do_not_use_ingestion_time():
    payload = make_payload(
        make_call_contract()
    )

    _, quotes = (
        normalize_massive_option_chain(
            "AAPL",
            payload,
        )
    )

    quote = quotes[0]

    assert quote["volume"] == 123
    assert quote["volume_at"] is None

    assert quote["open_interest"] == 456
    assert quote["open_interest_at"] is None


def test_missing_greeks_remain_unknown():
    contract = make_call_contract()

    contract["greeks"] = {}
    contract["implied_volatility"] = None

    payload = make_payload(
        contract
    )

    _, quotes = (
        normalize_massive_option_chain(
            "AAPL",
            payload,
        )
    )

    quote = quotes[0]

    assert quote["implied_volatility"] is None

    assert (
        quote["iv_source"]
        == PROVENANCE_UNKNOWN
    )

    assert quote["delta"] is None

    assert (
        quote["delta_source"]
        == PROVENANCE_UNKNOWN
    )

    assert quote["gamma"] is None

    assert (
        quote["gamma_source"]
        == PROVENANCE_UNKNOWN
    )

    assert quote["theta"] is None

    assert (
        quote["theta_source"]
        == PROVENANCE_UNKNOWN
    )

    assert quote["vega"] is None

    assert (
        quote["vega_source"]
        == PROVENANCE_UNKNOWN
    )


def test_real_zero_delta_is_fetched_not_unknown():
    contract = make_call_contract()

    contract["greeks"]["delta"] = 0

    payload = make_payload(
        contract
    )

    _, quotes = (
        normalize_massive_option_chain(
            "AAPL",
            payload,
        )
    )

    quote = quotes[0]

    assert quote["delta"] == 0

    assert (
        quote["delta_source"]
        == PROVENANCE_FETCHED
    )


def test_put_contract_is_normalized_to_p():
    contract = make_call_contract()

    contract["details"][
        "ticker"
    ] = "O:AAPL270115P00260000"

    contract["details"][
        "contract_type"
    ] = "put"

    payload = make_payload(
        contract
    )

    _, quotes = (
        normalize_massive_option_chain(
            "AAPL",
            payload,
        )
    )

    assert len(quotes) == 1
    assert quotes[0]["right"] == "P"


def test_incomplete_contracts_are_skipped():
    missing_strike = make_call_contract()

    missing_strike["details"].pop(
        "strike_price"
    )

    missing_expiry = make_call_contract()

    missing_expiry["details"].pop(
        "expiration_date"
    )

    invalid_type = make_call_contract()

    invalid_type["details"][
        "contract_type"
    ] = "banana"

    valid = make_call_contract()

    payload = make_payload(
        missing_strike,
        missing_expiry,
        invalid_type,
        valid,
    )

    _, quotes = (
        normalize_massive_option_chain(
            "AAPL",
            payload,
        )
    )

    assert len(quotes) == 1

    assert (
        quotes[0]["option_symbol"]
        == "O:AAPL270115C00260000"
    )


def test_client_rejects_invalid_requests():
    client = MassiveClient(
        api_key="fake-key"
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
            limit=251,
        )

    with pytest.raises(
        ValueError,
        match="contract_type",
    ):
        client.get_option_chain_page(
            "AAPL",
            contract_type="banana",
        )

    with pytest.raises(
        ValueError,
        match="min_dte cannot be negative",
    ):
        client.get_option_chain(
            "AAPL",
            min_dte=-1,
        )

    with pytest.raises(
        ValueError,
        match="max_dte cannot be smaller",
    ):
        client.get_option_chain(
            "AAPL",
            min_dte=30,
            max_dte=10,
        )

    with pytest.raises(
        ValueError,
        match="max_pages must be at least 1",
    ):
        client.get_option_chain(
            "AAPL",
            max_pages=0,
        )


def test_api_key_is_hidden_from_repr():
    client = MassiveClient(
        api_key="super-secret"
    )

    rendered = repr(client)

    assert "super-secret" not in rendered


def test_next_url_must_stay_on_massive_host():
    client = MassiveClient(
        api_key="fake-key"
    )

    with pytest.raises(
        MassiveUnsafeUrlError
    ):
        client._get_json_url(
            "https://evil.example/"
            "steal-my-key"
        )


def test_research_mode_rejects_truncation():
    class TruncatedClient(
        MassiveClient
    ):
        def __init__(self):
            super().__init__(
                api_key="fake-key"
            )

        def get_option_chain_page(
            self,
            underlying,
            **kwargs,
        ):
            return {
                "request_id":
                    "request-1",
                "results":
                    [],
                "status":
                    "OK",
                "next_url":
                    "https://api.massive.com/"
                    "next-page",
            }

        def _get_json_url(
            self,
            url,
        ):
            return {
                "request_id":
                    "request-2",
                "results":
                    [],
                "status":
                    "OK",
                "next_url":
                    "https://api.massive.com/"
                    "still-more",
            }

    client = TruncatedClient()

    with pytest.raises(
        MassiveTruncatedError,
        match="was truncated",
    ):
        client.get_option_chain(
            "AAPL",
            max_pages=2,
            require_complete=True,
            as_of_date=date(
                2026,
                8,
                27,
            ),
        )


def test_exploration_mode_can_report_truncation():
    class TruncatedClient(
        MassiveClient
    ):
        def __init__(self):
            super().__init__(
                api_key="fake-key"
            )

        def get_option_chain_page(
            self,
            underlying,
            **kwargs,
        ):
            return {
                "request_id":
                    "request-1",
                "results":
                    [],
                "status":
                    "OK",
                "next_url":
                    "https://api.massive.com/"
                    "next-page",
            }

        def _get_json_url(
            self,
            url,
        ):
            return {
                "request_id":
                    "request-2",
                "results":
                    [],
                "status":
                    "OK",
                "next_url":
                    "https://api.massive.com/"
                    "still-more",
            }

    client = TruncatedClient()

    payload = client.get_option_chain(
        "AAPL",
        max_pages=2,
        require_complete=False,
        as_of_date=date(
            2026,
            8,
            27,
        ),
    )

    assert payload["truncated"] is True
    assert payload["pages_fetched"] == 2


def test_chain_window_uses_supplied_reference_date():
    class WindowClient(
        MassiveClient
    ):
        def __init__(self):
            super().__init__(
                api_key="fake-key"
            )

            self.params = None

        def get_option_chain_page(
            self,
            underlying,
            **kwargs,
        ):
            self.params = {
                "underlying":
                    underlying,
                **kwargs,
            }

            return {
                "request_id":
                    "request-1",
                "results":
                    [],
                "status":
                    "OK",
                "next_url":
                    None,
            }

    client = WindowClient()

    payload = client.get_option_chain(
        "aapl",
        min_dte=7,
        max_dte=45,
        as_of_date=date(
            2026,
            8,
            27,
        ),
    )

    assert (
        client.params[
            "expiration_date_gte"
        ]
        == "2026-09-03"
    )

    assert (
        client.params[
            "expiration_date_lte"
        ]
        == "2026-10-11"
    )

    assert (
        client.params["underlying"]
        == "aapl"
    )

    assert payload["truncated"] is False

    assert (
        payload["reference_date"]
        == "2026-08-27"
    )

    assert (
        payload["reference_timezone"]
        == "America/New_York"
    )


def test_all_request_ids_are_retained_in_notes():
    payload = make_payload(
        make_call_contract()
    )

    payload["request_ids"] = [
        "request-1",
        "request-2",
        "request-3",
    ]

    snapshot, _ = (
        normalize_massive_option_chain(
            "AAPL",
            payload,
        )
    )

    assert (
        "request-1,request-2,request-3"
        in snapshot["notes"]
    )