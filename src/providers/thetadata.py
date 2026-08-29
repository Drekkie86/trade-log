"""
Read-only ThetaData v3 evaluation client for Christiania.

Purpose:
- validate historical EOD option-chain access;
- flatten ThetaData's contract/data envelope into canonical-like rows;
- preserve provider provenance before schema integration.

No database writes. No broker calls. No orders.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import json
from typing import Any, Callable, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class ThetaDataError(RuntimeError):
    pass


class ThetaDataUnavailable(ThetaDataError):
    pass


class ThetaDataResponseError(ThetaDataError):
    pass


Transport = Callable[[str, float], bytes]


def _default_transport(url: str, timeout: float) -> bytes:
    request = Request(
        url,
        headers={"Accept": "application/json"},
        method="GET",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.read()
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise ThetaDataResponseError(
            f"ThetaData HTTP {exc.code}: {body[:800]}"
        ) from exc
    except URLError as exc:
        raise ThetaDataUnavailable(
            "Could not reach Theta Terminal at the configured base URL."
        ) from exc


@dataclass(frozen=True)
class ThetaDataClient:
    base_url: str = "http://127.0.0.1:25503/v3"
    timeout_seconds: float = 60.0
    transport: Transport = _default_transport

    def _get_payload(
        self,
        path: str,
        params: Mapping[str, object],
    ) -> Any:
        clean = {
            key: str(value)
            for key, value in params.items()
            if value is not None
        }
        clean["format"] = "json"

        url = (
            self.base_url.rstrip("/")
            + "/"
            + path.lstrip("/")
            + "?"
            + urlencode(clean)
        )

        raw = self.transport(url, self.timeout_seconds)

        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ThetaDataResponseError(
                "ThetaData did not return valid JSON."
            ) from exc

    def option_eod_chain_raw(
        self,
        symbol: str,
        trading_date: date,
        *,
        max_dte: int | None = 45,
        strike_range: int | None = None,
    ) -> tuple[dict[str, Any], ...]:
        payload = self._get_payload(
            "/option/history/eod",
            {
                "symbol": symbol.upper(),
                "expiration": "*",
                "start_date": trading_date.isoformat(),
                "end_date": trading_date.isoformat(),
                "max_dte": max_dte,
                "strike_range": strike_range,
            },
        )

        if isinstance(payload, list):
            rows = payload
        elif isinstance(payload, dict) and isinstance(payload.get("response"), list):
            rows = payload["response"]
        else:
            raise ThetaDataResponseError(
                "Unexpected ThetaData payload shape: expected a list or "
                "an object with list-valued 'response'."
            )

        result: list[dict[str, Any]] = []
        for index, item in enumerate(rows):
            if not isinstance(item, dict):
                raise ThetaDataResponseError(
                    f"Unexpected ThetaData response row {index}: expected object."
                )
            result.append(dict(item))
        return tuple(result)

    def option_eod_chain_flat(
        self,
        symbol: str,
        trading_date: date,
        *,
        max_dte: int | None = 45,
        strike_range: int | None = None,
    ) -> tuple[dict[str, Any], ...]:
        rows = self.option_eod_chain_raw(
            symbol,
            trading_date,
            max_dte=max_dte,
            strike_range=strike_range,
        )

        flat: list[dict[str, Any]] = []

        for index, row in enumerate(rows):
            contract = row.get("contract")
            data = row.get("data")

            if not isinstance(contract, dict):
                raise ThetaDataResponseError(
                    f"ThetaData row {index} missing contract object."
                )
            if not isinstance(data, list):
                raise ThetaDataResponseError(
                    f"ThetaData row {index} missing data list."
                )

            if len(data) != 1:
                raise ThetaDataResponseError(
                    f"ThetaData row {index} expected exactly one EOD data row; "
                    f"got {len(data)}."
                )

            observation = data[0]
            if not isinstance(observation, dict):
                raise ThetaDataResponseError(
                    f"ThetaData row {index} EOD observation is not an object."
                )

            merged = {
                "provider": "THETADATA",
                "underlying": str(contract.get("symbol", symbol)).upper(),
                "expiration": contract.get("expiration"),
                "strike": contract.get("strike"),
                "right": str(contract.get("right", "")).upper(),
                **observation,
            }
            flat.append(merged)

        return tuple(flat)


def theta_identity_key(row: Mapping[str, Any]) -> tuple[str, str, float, str]:
    try:
        underlying = str(row["underlying"]).upper()
        expiration = str(row["expiration"])
        strike = float(row["strike"])
        right = str(row["right"]).upper()
    except (KeyError, TypeError, ValueError) as exc:
        raise ThetaDataResponseError(
            f"Cannot build ThetaData identity key from row: {row}"
        ) from exc

    if right not in {"CALL", "PUT"}:
        raise ThetaDataResponseError(
            f"Unexpected ThetaData right: {right}"
        )

    return underlying, expiration, strike, right
