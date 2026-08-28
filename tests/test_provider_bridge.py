import pytest

from src.providers.bridge import (
    ContractIdentityError,
    OptionBridgeError,
    bridge_massive_quote_to_saxo,
)
from src.providers.saxo import (
    QuoteQuality,
    SaxoOptionContract,
    SaxoOptionQuote,
)


class FakeSaxoClient:
    def __init__(self):
        self.calls = []

    def get_option_contract_and_quote(
        self,
        underlying,
        expiration,
        strike,
        put_call,
    ):
        self.calls.append(
            {
                "underlying": underlying,
                "expiration": expiration,
                "strike": strike,
                "put_call": put_call,
            }
        )

        contract = SaxoOptionContract(
            uic=44557464,
            option_root_id=309,
            underlying_uic=211,
            underlying=underlying.upper(),
            put_call=put_call,
            strike=float(strike),
            expiration=expiration,
            trading_status="Tradable",
            contract_size=100.0,
        )

        quote = SaxoOptionQuote(
            uic=44557464,
            bid=62.20,
            ask=63.85,
            mid=63.025,
            bid_size=0.0,
            ask_size=0.0,
            delayed_by_minutes=15,
            market_state="Closed",
            price_source="OPRA",
            price_source_type="Firm",
            price_type_bid="OldIndicative",
            price_type_ask="OldIndicative",
            last_updated=(
                "2026-08-27T21:10:34.311000Z"
            ),
        )

        return contract, quote


def make_massive_quote():
    return {
        "provider_contract_id":
            "O:AAPL270115C00260000",
        "option_symbol":
            "O:AAPL270115C00260000",
        "expiration": "2027-01-15",
        "right": "C",
        "strike": 260.0,
        "shares_per_contract": 100,
        "bid": None,
        "ask": None,
        "implied_volatility": 0.35,
        "delta": 0.55,
        "open_interest": 1234,
    }


def test_bridge_resolves_massive_contract():
    client = FakeSaxoClient()

    result = bridge_massive_quote_to_saxo(
        saxo_client=client,
        underlying="AAPL",
        massive_quote=make_massive_quote(),
    )

    assert result.underlying == "AAPL"
    assert result.expiration == "2027-01-15"
    assert result.strike == 260.0
    assert result.right == "Call"
    assert result.saxo_contract.uic == 44557464


def test_bridge_calls_saxo_with_massive_identity():
    client = FakeSaxoClient()

    bridge_massive_quote_to_saxo(
        saxo_client=client,
        underlying="AAPL",
        massive_quote=make_massive_quote(),
    )

    assert client.calls == [
        {
            "underlying": "AAPL",
            "expiration": "2027-01-15",
            "strike": 260.0,
            "put_call": "Call",
        }
    ]


def test_bridge_preserves_massive_research_data():
    client = FakeSaxoClient()

    result = bridge_massive_quote_to_saxo(
        saxo_client=client,
        underlying="AAPL",
        massive_quote=make_massive_quote(),
    )

    assert (
        result.massive_symbol
        == "O:AAPL270115C00260000"
    )

    assert result.massive_bid is None
    assert result.massive_ask is None
    assert result.massive_iv == 0.35
    assert result.massive_delta == 0.55
    assert result.massive_open_interest == 1234

    assert (
        result.massive_shares_per_contract
        == 100.0
    )


def test_bridge_exposes_saxo_market_evidence():
    client = FakeSaxoClient()

    result = bridge_massive_quote_to_saxo(
        saxo_client=client,
        underlying="AAPL",
        massive_quote=make_massive_quote(),
    )

    assert result.saxo_bid == 62.20
    assert result.saxo_ask == 63.85
    assert result.saxo_mid == 63.025

    assert result.saxo_spread == pytest.approx(
        1.65
    )

    assert (
        result.saxo_spread_pct_mid
        == pytest.approx(
            1.65 / ((62.20 + 63.85) / 2)
        )
    )


def test_bridge_does_not_call_stale_quote_executable():
    client = FakeSaxoClient()

    result = bridge_massive_quote_to_saxo(
        saxo_client=client,
        underlying="AAPL",
        massive_quote=make_massive_quote(),
    )

    assert (
        result.quote_quality
        == QuoteQuality.STALE
    )

    assert result.is_executable is False


def test_put_is_normalized_for_saxo():
    client = FakeSaxoClient()

    massive_quote = make_massive_quote()

    massive_quote["right"] = "P"

    result = bridge_massive_quote_to_saxo(
        saxo_client=client,
        underlying="AAPL",
        massive_quote=massive_quote,
    )

    assert result.right == "Put"

    assert (
        client.calls[0]["put_call"]
        == "Put"
    )


def test_full_words_are_accepted():
    client = FakeSaxoClient()

    massive_quote = make_massive_quote()

    massive_quote["right"] = "call"

    result = bridge_massive_quote_to_saxo(
        saxo_client=client,
        underlying="AAPL",
        massive_quote=massive_quote,
    )

    assert result.right == "Call"


def test_missing_required_field_fails():
    client = FakeSaxoClient()

    massive_quote = make_massive_quote()

    massive_quote.pop("strike")

    with pytest.raises(
        OptionBridgeError,
        match="missing required field: strike",
    ):
        bridge_massive_quote_to_saxo(
            saxo_client=client,
            underlying="AAPL",
            massive_quote=massive_quote,
        )


def test_unknown_right_fails():
    client = FakeSaxoClient()

    massive_quote = make_massive_quote()

    massive_quote["right"] = "banana"

    with pytest.raises(
        OptionBridgeError,
        match="Unsupported option right",
    ):
        bridge_massive_quote_to_saxo(
            saxo_client=client,
            underlying="AAPL",
            massive_quote=massive_quote,
        )


def test_missing_saxo_market_stays_missing():
    class NoMarketSaxoClient(
        FakeSaxoClient
    ):
        def get_option_contract_and_quote(
            self,
            underlying,
            expiration,
            strike,
            put_call,
        ):
            (
                contract,
                quote,
            ) = super().get_option_contract_and_quote(
                underlying,
                expiration,
                strike,
                put_call,
            )

            missing_quote = SaxoOptionQuote(
                uic=quote.uic,
                bid=None,
                ask=None,
                mid=None,
                bid_size=None,
                ask_size=None,
                delayed_by_minutes=None,
                market_state=None,
                price_source="OPRA",
                price_source_type=None,
                price_type_bid="NoAccess",
                price_type_ask="NoAccess",
                last_updated=None,
            )

            return (
                contract,
                missing_quote,
            )

    client = NoMarketSaxoClient()

    result = bridge_massive_quote_to_saxo(
        saxo_client=client,
        underlying="AAPL",
        massive_quote=make_massive_quote(),
    )

    assert result.saxo_bid is None
    assert result.saxo_ask is None
    assert result.saxo_spread is None

    assert (
        result.quote_quality
        == QuoteQuality.UNAVAILABLE
    )

    assert result.is_executable is False


def test_multiplier_match_is_preserved():
    client = FakeSaxoClient()

    result = bridge_massive_quote_to_saxo(
        saxo_client=client,
        underlying="AAPL",
        massive_quote=make_massive_quote(),
    )

    assert (
        result.massive_shares_per_contract
        == 100.0
    )

    assert (
        result.saxo_contract.contract_size
        == 100.0
    )


def test_multiplier_mismatch_is_rejected():
    client = FakeSaxoClient()

    massive_quote = make_massive_quote()

    massive_quote[
        "shares_per_contract"
    ] = 50

    with pytest.raises(
        ContractIdentityError,
        match="Contract multiplier mismatch",
    ):
        bridge_massive_quote_to_saxo(
            saxo_client=client,
            underlying="AAPL",
            massive_quote=massive_quote,
        )


def test_missing_massive_multiplier_is_rejected():
    client = FakeSaxoClient()

    massive_quote = make_massive_quote()

    massive_quote[
        "shares_per_contract"
    ] = None

    with pytest.raises(
        ContractIdentityError,
        match="Massive contract multiplier is missing",
    ):
        bridge_massive_quote_to_saxo(
            saxo_client=client,
            underlying="AAPL",
            massive_quote=massive_quote,
        )


def test_missing_saxo_multiplier_is_rejected():
    class MissingMultiplierSaxoClient(
        FakeSaxoClient
    ):
        def get_option_contract_and_quote(
            self,
            underlying,
            expiration,
            strike,
            put_call,
        ):
            (
                contract,
                quote,
            ) = super().get_option_contract_and_quote(
                underlying,
                expiration,
                strike,
                put_call,
            )

            missing_multiplier_contract = (
                SaxoOptionContract(
                    uic=contract.uic,
                    option_root_id=(
                        contract.option_root_id
                    ),
                    underlying_uic=(
                        contract.underlying_uic
                    ),
                    underlying=(
                        contract.underlying
                    ),
                    put_call=(
                        contract.put_call
                    ),
                    strike=contract.strike,
                    expiration=(
                        contract.expiration
                    ),
                    trading_status=(
                        contract.trading_status
                    ),
                    contract_size=None,
                )
            )

            return (
                missing_multiplier_contract,
                quote,
            )

    client = MissingMultiplierSaxoClient()

    with pytest.raises(
        ContractIdentityError,
        match="Saxo contract multiplier is missing",
    ):
        bridge_massive_quote_to_saxo(
            saxo_client=client,
            underlying="AAPL",
            massive_quote=make_massive_quote(),
        )