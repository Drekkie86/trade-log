import pytest

from src.providers.ecb_fx import (
    EcbFxError,
    parse_ecb_eurusd_xml,
)


XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<gesmes:Envelope
 xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01"
 xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
 <Cube>
  <Cube time="2026-09-01">
   <Cube currency="USD" rate="1.1700"/>
   <Cube currency="GBP" rate="0.8600"/>
  </Cube>
 </Cube>
</gesmes:Envelope>
"""


def test_parse_ecb_eurusd():
    result = parse_ecb_eurusd_xml(
        XML,
        observed_at=
            "2026-09-01T12:00:00Z",
    )

    assert result.provider == "ECB"
    assert result.base_currency == "EUR"
    assert result.quote_currency == "USD"
    assert result.rate == pytest.approx(
        1.17
    )
    assert (
        result.reference_date
        == "2026-09-01"
    )


def test_parse_ecb_missing_usd_fails():
    payload = XML.replace(
        b'currency="USD"',
        b'currency="CAD"',
    )

    with pytest.raises(
        EcbFxError,
        match="USD",
    ):
        parse_ecb_eurusd_xml(
            payload,
            observed_at=
                "2026-09-01T12:00:00Z",
        )
