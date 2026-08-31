from __future__ import annotations

from datetime import date
from typing import Any, Mapping

from src.providers.thetadata import (
    ThetaDataClient,
    ThetaDataResponseError,
)


def _flatten_snapshot_payload(
    payload: Any,
) -> tuple[dict[str, Any], ...]:
    if isinstance(payload, list):
        rows = payload
    elif (
        isinstance(payload, dict)
        and isinstance(payload.get("response"), list)
    ):
        rows = payload["response"]
    else:
        raise ThetaDataResponseError(
            "Unexpected ThetaData snapshot payload shape."
        )

    flat: list[dict[str, Any]] = []

    for index, item in enumerate(rows):
        if not isinstance(item, dict):
            raise ThetaDataResponseError(
                f"Snapshot row {index} is not an object."
            )

        contract = item.get("contract")
        data = item.get("data")

        if isinstance(contract, dict) and isinstance(data, list):
            for observation in data:
                if not isinstance(observation, dict):
                    raise ThetaDataResponseError(
                        f"Snapshot row {index} contains non-object data."
                    )
                flat.append({**contract, **observation})
        else:
            flat.append(dict(item))

    return tuple(flat)


def _normalize_right(value: Any) -> str:
    right = str(value or "").strip().upper()
    if right in {"C", "CALL"}:
        return "C"
    if right in {"P", "PUT"}:
        return "P"
    raise ThetaDataResponseError(
        f"Unexpected ThetaData option right: {value}"
    )


def _normalize_snapshot_rows(
    rows: tuple[dict[str, Any], ...],
    *,
    symbol: str,
    quote_age_by_identity:
        Mapping[tuple[str, str, float, str], float | None]
        | None = None,
) -> tuple[dict[str, Any], ...]:
    normalized: list[dict[str, Any]] = []

    for row in rows:
        try:
            expiration = str(row["expiration"])
            strike = float(row["strike"])
            right = _normalize_right(row["right"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ThetaDataResponseError(
                f"Cannot normalize ThetaData snapshot row: {row}"
            ) from exc

        identity = (
            symbol.upper(),
            expiration,
            strike,
            right,
        )

        item = {
            "underlying": symbol.upper(),
            "expiration": expiration,
            "strike": strike,
            "right": right,
            **row,
        }

        item["underlying"] = symbol.upper()
        item["expiration"] = expiration
        item["strike"] = strike
        item["right"] = right
        item["raw_timestamp"] = (
            row.get("timestamp")
            or row.get("quote_timestamp")
            or row.get("underlying_timestamp")
        )

        if quote_age_by_identity is not None:
            item["quote_age_seconds"] = (
                quote_age_by_identity.get(identity)
            )

        normalized.append(item)

    return tuple(normalized)


def fetch_live_quote_rows(
    client: ThetaDataClient,
    symbol: str,
) -> tuple[dict[str, Any], ...]:
    payload = client._get_payload(
        "/option/snapshot/quote",
        {
            "symbol": symbol.upper(),
            "expiration": "*",
            "strike": "*",
            "right": "both",
        },
    )
    return _normalize_snapshot_rows(
        _flatten_snapshot_payload(payload),
        symbol=symbol,
    )


def fetch_live_first_order_greek_rows(
    client: ThetaDataClient,
    symbol: str,
) -> tuple[dict[str, Any], ...]:
    payload = client._get_payload(
        "/option/snapshot/greeks/first_order",
        {
            "symbol": symbol.upper(),
            "expiration": "*",
            "strike": "*",
            "right": "both",
            "version": "latest",
        },
    )
    return _normalize_snapshot_rows(
        _flatten_snapshot_payload(payload),
        symbol=symbol,
    )


def filter_dte_window(
    rows: tuple[dict[str, Any], ...],
    *,
    reference_date: date,
    min_dte: int = 7,
    max_dte: int = 45,
) -> tuple[dict[str, Any], ...]:
    result: list[dict[str, Any]] = []

    for row in rows:
        expiration = date.fromisoformat(
            str(row["expiration"])
        )
        dte = (expiration - reference_date).days
        if min_dte <= dte <= max_dte:
            result.append(dict(row))

    return tuple(result)
