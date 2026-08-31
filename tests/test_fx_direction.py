from src.providers.ecb_fx import EcbFxObservation
from src.research.shadow_admission import _to_eur_minor


def test_usd_to_eur_conversion_direction_matches_ecb_quote():
    # ECB convention:
    # 1 EUR = 1.20 USD.
    # Therefore 120.00 USD = 100.00 EUR.
    assert _to_eur_minor(
        12_000,
        eur_to_usd=1.20,
    ) == 10_000


def test_ecb_observation_semantics_are_eur_base_usd_quote():
    fx = EcbFxObservation(
        provider="ECB",
        base_currency="EUR",
        quote_currency="USD",
        rate=1.20,
        reference_date="2026-09-01",
        observed_at="2026-09-01T12:00:00Z",
        source_url="https://example.test/ecb",
        provenance="ECB_DAILY_REFERENCE_RATE",
    )

    assert fx.base_currency == "EUR"
    assert fx.quote_currency == "USD"
    assert fx.rate == 1.20
