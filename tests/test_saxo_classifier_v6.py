import pytest

from src.providers.saxo import (
    QuoteQuality,
    SaxoOptionQuote,
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


def test_zero_bid_is_unavailable():
    quote = make_quote(
        bid=0.0,
        ask=0.10,
    )

    assert (
        quote.quality
        == QuoteQuality.UNAVAILABLE
    )

    assert (
        quote.is_executable
        is False
    )


def test_crossed_quote_is_unavailable():
    quote = make_quote(
        bid=10.30,
        ask=10.20,
    )

    assert (
        quote.is_crossed
        is True
    )

    assert (
        quote.quality
        == QuoteQuality.UNAVAILABLE
    )

    assert (
        quote.is_executable
        is False
    )


def test_locked_quote_is_not_automatically_invalid():
    quote = make_quote(
        bid=10.20,
        ask=10.20,
    )

    assert (
        quote.is_locked
        is True
    )

    assert (
        quote.is_crossed
        is False
    )

    assert (
        quote.quality
        == QuoteQuality.EXECUTABLE
    )

    assert (
        quote.is_executable
        is True
    )


def test_stale_and_indicative_can_both_be_true():
    quote = make_quote(
        market_state="Closed",
        delayed_by_minutes=15,
        price_source_type="Indicative",
        price_type_bid="OldIndicative",
        price_type_ask="OldIndicative",
    )

    assert quote.is_stale is True
    assert quote.is_indicative is True
    assert quote.is_delayed is True

    # Summary label remains one convenient label,
    # but the independent flags are canonical.
    assert (
        quote.quality
        == QuoteQuality.STALE
    )


def test_delayed_flag_is_independent():
    quote = make_quote(
        delayed_by_minutes=15,
    )

    assert quote.is_stale is False
    assert quote.is_indicative is False
    assert quote.is_delayed is True

    assert (
        quote.quality
        == QuoteQuality.DELAYED
    )


def test_non_firm_flag_is_indicative():
    quote = make_quote(
        price_source_type="Indicative",
    )

    assert (
        quote.is_indicative
        is True
    )

    assert (
        quote.quality
        == QuoteQuality.INDICATIVE
    )


@pytest.mark.parametrize(
    "missing_side",
    [
        "bid",
        "ask",
    ],
)
def test_missing_price_is_unavailable(
    missing_side,
):
    kwargs = {}

    kwargs[
        missing_side
    ] = None

    quote = make_quote(
        **kwargs
    )

    assert (
        quote.quality
        == QuoteQuality.UNAVAILABLE
    )
