from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from urllib.request import Request, urlopen
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

UTC = ZoneInfo("UTC")

ECB_DAILY_XML_URL = (
    "https://www.ecb.europa.eu/stats/eurofxref/"
    "eurofxref-daily.xml"
)


class EcbFxError(RuntimeError):
    pass


@dataclass(frozen=True)
class EcbFxObservation:
    provider: str
    base_currency: str
    quote_currency: str
    rate: float
    reference_date: str
    observed_at: str
    source_url: str
    provenance: str


def parse_ecb_eurusd_xml(
    xml_bytes: bytes,
    *,
    observed_at: str,
) -> EcbFxObservation:
    try:
        root = ElementTree.fromstring(
            xml_bytes
        )
    except ElementTree.ParseError as exc:
        raise EcbFxError(
            "ECB FX XML could not be parsed."
        ) from exc

    dated_cubes = [
        element
        for element in root.iter()
        if element.tag.endswith("Cube")
        and element.attrib.get("time")
    ]

    if len(dated_cubes) != 1:
        raise EcbFxError(
            "ECB FX XML did not contain exactly one "
            "daily reference-date cube."
        )

    dated = dated_cubes[0]
    reference_date = dated.attrib["time"]

    usd_rows = [
        child
        for child in list(dated)
        if child.attrib.get("currency") == "USD"
    ]

    if len(usd_rows) != 1:
        raise EcbFxError(
            "ECB FX XML did not contain exactly one USD rate."
        )

    try:
        eur_to_usd = float(
            usd_rows[0].attrib["rate"]
        )
    except (KeyError, ValueError) as exc:
        raise EcbFxError(
            "ECB USD rate is invalid."
        ) from exc

    if eur_to_usd <= 0:
        raise EcbFxError(
            "ECB USD rate must be positive."
        )

    return EcbFxObservation(
        provider="ECB",
        base_currency="EUR",
        quote_currency="USD",
        rate=eur_to_usd,
        reference_date=reference_date,
        observed_at=observed_at,
        source_url=ECB_DAILY_XML_URL,
        provenance="ECB_DAILY_REFERENCE_RATE",
    )


def fetch_ecb_eurusd(
    *,
    timeout_seconds: float = 10.0,
) -> EcbFxObservation:
    observed_at = datetime.now(
        UTC
    ).isoformat(
        timespec="milliseconds"
    ).replace("+00:00", "Z")

    request = Request(
        ECB_DAILY_XML_URL,
        headers={
            "User-Agent":
                "ChristianiaResearch/1.0",
        },
    )

    try:
        with urlopen(
            request,
            timeout=timeout_seconds,
        ) as response:
            payload = response.read()
    except Exception as exc:
        raise EcbFxError(
            "ECB daily FX reference rate could not be fetched."
        ) from exc

    return parse_ecb_eurusd_xml(
        payload,
        observed_at=observed_at,
    )
