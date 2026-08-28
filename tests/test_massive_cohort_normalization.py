from src.providers.massive import (
    normalize_massive_option_chain_for_research,
)


def make_payload():
    return {
        "request_id": "request-123",
        "request_ids": [
            "request-123",
        ],
        "reference_date": "2026-08-28",
        "pages_fetched": 1,
        "truncated": False,
        "results": [
            {
                "details": {
                    "ticker":
                        "O:AAPL260918C00320000",
                    "contract_type": "call",
                    "strike_price": 320,
                    "expiration_date":
                        "2026-09-18",
                    "shares_per_contract":
                        100,
                },
                "implied_volatility": 0.25,
                "greeks": {
                    "delta": 0.41,
                    "gamma": 0.01,
                    "theta": -0.20,
                    "vega": 0.30,
                },
                "day": {
                    "volume": 17,
                },
                "open_interest": 35202,
            },
            {
                "details": {
                    "ticker":
                        "O:AAPL260918X00320000",
                    "contract_type":
                        "other",
                    "strike_price": 320,
                    "expiration_date":
                        "2026-09-18",
                },
            },
            {
                "details": {
                    "ticker":
                        "O:AAPL260918P00300000",
                    "contract_type": "put",
                    "strike_price": None,
                    "expiration_date":
                        "2026-09-18",
                },
            },
        ],
    }


def test_research_normalization_reconciles():
    result = (
        normalize_massive_option_chain_for_research(
            "AAPL",
            make_payload(),
        )
    )

    assert result.raw_contract_count == 3
    assert result.normalized_contract_count == 1
    assert result.drop_count == 2

    assert (
        result.normalized_contract_count
        + result.drop_count
        == result.raw_contract_count
    )

    assert result.drop_reason_counts == {
        "UNSUPPORTED_CONTRACT_TYPE": 1,
        "MISSING_STRIKE": 1,
    }


def test_research_quote_does_not_duplicate_model_fields():
    result = (
        normalize_massive_option_chain_for_research(
            "AAPL",
            make_payload(),
        )
    )

    quote = result.quotes[0]

    assert (
        quote["implied_volatility"]
        is None
    )
    assert quote["iv_source"] == "UNKNOWN"

    assert quote["delta"] is None
    assert quote["delta_source"] == "UNKNOWN"

    assert quote["gamma"] is None
    assert quote["theta"] is None
    assert quote["vega"] is None


def test_provider_model_output_is_separate():
    result = (
        normalize_massive_option_chain_for_research(
            "AAPL",
            make_payload(),
        )
    )

    assert len(
        result.model_observations
    ) == 1

    model = (
        result.model_observations[0]
    )

    assert (
        model.provider_contract_id
        == "O:AAPL260918C00320000"
    )

    assert (
        model.implied_volatility
        == 0.25
    )

    assert model.delta == 0.41

    assert model.observed_at is None
    assert (
        model.model_underlying_price
        is None
    )
    assert model.model_rate is None


def test_volume_has_explicit_trading_date():
    result = (
        normalize_massive_option_chain_for_research(
            "AAPL",
            make_payload(),
        )
    )

    quote = result.quotes[0]

    assert (
        quote["volume_trading_date"]
        == "2026-08-28"
    )

    # OI effective date remains unknown because
    # the provider payload does not supply one.
    assert (
        quote["open_interest_as_of_date"]
        is None
    )


def test_missing_identifier_is_logged():
    payload = make_payload()

    payload["results"] = [
        {
            "details": {
                "contract_type": "call",
                "strike_price": 320,
                "expiration_date":
                    "2026-09-18",
            },
        },
    ]

    result = (
        normalize_massive_option_chain_for_research(
            "AAPL",
            payload,
        )
    )

    assert result.normalized_contract_count == 0
    assert result.drop_count == 1

    assert (
        result.drops[0].reason_code
        == "MISSING_CONTRACT_IDENTIFIER"
    )


def test_invalid_strike_is_logged():
    payload = make_payload()

    payload["results"] = [
        {
            "details": {
                "ticker":
                    "O:AAPL260918C00320000",
                "contract_type": "call",
                "strike_price": "not-a-number",
                "expiration_date":
                    "2026-09-18",
            },
        },
    ]

    result = (
        normalize_massive_option_chain_for_research(
            "AAPL",
            payload,
        )
    )

    assert result.drop_count == 1

    assert (
        result.drops[0].reason_code
        == "INVALID_STRIKE"
    )
