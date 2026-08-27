from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import (
    date,
    datetime,
    timedelta,
    timezone,
)
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen


MASSIVE_BASE_URL = "https://api.massive.com"

PROVENANCE_FETCHED = "FETCHED"
PROVENANCE_UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class MassiveClient:
    api_key: str
    base_url: str = MASSIVE_BASE_URL
    timeout_seconds: int = 30

    def _get_json_url(
        self,
        url: str,
    ) -> dict[str, Any]:

        request = Request(
            url,
            headers={
                "Authorization":
                    f"Bearer {self.api_key}",

                "Accept":
                    "application/json",

                "User-Agent":
                    "Christiania/0.1",
            },
            method="GET",
        )

        with urlopen(
            request,
            timeout=self.timeout_seconds,
        ) as response:

            payload = response.read().decode(
                "utf-8"
            )

        return json.loads(
            payload
        )

    def _get_json(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:

        params = params or {}

        query = urlencode(
            {
                key: value
                for key, value in params.items()
                if value is not None
            }
        )

        url = (
            f"{self.base_url}{path}"
            + (
                f"?{query}"
                if query
                else ""
            )
        )

        return self._get_json_url(
            url
        )

    def get_option_chain_page(
        self,
        underlying: str,
        *,
        limit: int = 250,
        order: str = "asc",
        sort: str = "ticker",
        expiration_date_gte: str | None = None,
        expiration_date_lte: str | None = None,
        contract_type: str | None = None,
    ) -> dict[str, Any]:

        symbol = underlying.strip().upper()

        if not symbol:
            raise ValueError(
                "Underlying cannot be blank."
            )

        if limit < 1 or limit > 250:
            raise ValueError(
                "Massive option-chain limit "
                "must be between 1 and 250."
            )

        if contract_type not in {
            None,
            "call",
            "put",
        }:
            raise ValueError(
                "contract_type must be "
                "call, put, or None."
            )

        return self._get_json(
            f"/v3/snapshot/options/{symbol}",
            params={
                "limit":
                    limit,

                "order":
                    order,

                "sort":
                    sort,

                "expiration_date.gte":
                    expiration_date_gte,

                "expiration_date.lte":
                    expiration_date_lte,

                "contract_type":
                    contract_type,
            },
        )

    def get_option_chain(
        self,
        underlying: str,
        *,
        min_dte: int = 7,
        max_dte: int = 45,
        contract_type: str | None = None,
        page_limit: int = 250,
        max_pages: int = 20,
        as_of_date: date | None = None,
    ) -> dict[str, Any]:
        """
        Fetch a paginated option-chain window.

        By default Christiania requests contracts with
        7-45 calendar days to expiration.

        Results from every returned page are combined
        into one Massive-shaped payload.
        """

        if min_dte < 0:
            raise ValueError(
                "min_dte cannot be negative."
            )

        if max_dte < min_dte:
            raise ValueError(
                "max_dte cannot be smaller "
                "than min_dte."
            )

        if max_pages < 1:
            raise ValueError(
                "max_pages must be at least 1."
            )

        if page_limit < 1 or page_limit > 250:
            raise ValueError(
                "Massive option-chain page limit "
                "must be between 1 and 250."
            )

        reference_date = (
            as_of_date
            or datetime.now(
                timezone.utc
            ).date()
        )

        expiration_gte = (
            reference_date
            + timedelta(
                days=min_dte
            )
        ).isoformat()

        expiration_lte = (
            reference_date
            + timedelta(
                days=max_dte
            )
        ).isoformat()

        first_page = self.get_option_chain_page(
            underlying,
            limit=page_limit,
            order="asc",
            sort="ticker",
            expiration_date_gte=expiration_gte,
            expiration_date_lte=expiration_lte,
            contract_type=contract_type,
        )

        combined_results = list(
            first_page.get(
                "results"
            )
            or []
        )

        request_ids = []

        first_request_id = (
            first_page.get(
                "request_id"
            )
        )

        if first_request_id:
            request_ids.append(
                first_request_id
            )

        next_url = first_page.get(
            "next_url"
        )

        pages_fetched = 1

        while (
            next_url
            and pages_fetched < max_pages
        ):
            page = self._get_json_url(
                next_url
            )

            combined_results.extend(
                page.get(
                    "results"
                )
                or []
            )

            request_id = page.get(
                "request_id"
            )

            if request_id:
                request_ids.append(
                    request_id
                )

            next_url = page.get(
                "next_url"
            )

            pages_fetched += 1

        return {
            "request_id":
                first_request_id,

            "request_ids":
                request_ids,

            "results":
                combined_results,

            "status":
                first_page.get(
                    "status"
                ),

            "next_url":
                next_url,

            "pages_fetched":
                pages_fetched,

            "window_min_dte":
                min_dte,

            "window_max_dte":
                max_dte,

            "window_expiration_gte":
                expiration_gte,

            "window_expiration_lte":
                expiration_lte,

            "truncated":
                bool(next_url),
        }


def _iso_now() -> str:
    return (
        datetime.now(
            timezone.utc
        )
        .replace(
            microsecond=0
        )
        .isoformat()
        .replace(
            "+00:00",
            "Z",
        )
    )


def _nanoseconds_to_iso(
    value: int | None,
) -> str | None:
    if value is None:
        return None

    seconds = (
        int(value)
        / 1_000_000_000
    )

    return (
        datetime.fromtimestamp(
            seconds,
            tz=timezone.utc,
        )
        .replace(
            microsecond=0
        )
        .isoformat()
        .replace(
            "+00:00",
            "Z",
        )
    )


def _value_and_source(
    value: Any,
) -> tuple[Any, str]:
    if value is None:
        return (
            None,
            PROVENANCE_UNKNOWN,
        )

    return (
        value,
        PROVENANCE_FETCHED,
    )


def normalize_massive_option_chain(
    underlying: str,
    payload: dict[str, Any],
) -> tuple[
    dict[str, Any],
    list[dict[str, Any]],
]:
    """
    Convert Massive option-chain data into
    Christiania's normalized research representation.

    Missing values remain:
        None + UNKNOWN

    No database writes happen here.
    """

    symbol = underlying.strip().upper()

    if not symbol:
        raise ValueError(
            "Underlying cannot be blank."
        )

    results = payload.get(
        "results"
    ) or []

    captured_at = _iso_now()

    underlying_price = None
    underlying_at = None

    for item in results:
        underlying_asset = (
            item.get(
                "underlying_asset"
            )
            or {}
        )

        price = underlying_asset.get(
            "price"
        )

        if price is not None:
            underlying_price = price

            underlying_at = (
                _nanoseconds_to_iso(
                    underlying_asset.get(
                        "last_updated"
                    )
                )
            )

            break

    (
        normalized_underlying_price,
        underlying_source,
    ) = _value_and_source(
        underlying_price
    )

    snapshot = {
        "captured_at":
            captured_at,

        "underlying":
            symbol,

        "provider":
            "MASSIVE",

        "provider_snapshot_id":
            payload.get(
                "request_id"
            ),

        "underlying_price":
            normalized_underlying_price,

        "underlying_source":
            underlying_source,

        "underlying_at":
            underlying_at,

        "fx_to_eur":
            None,

        "fx_source":
            "UNKNOWN",

        "fx_at":
            None,

        "notes":
            (
                "Normalized from Massive "
                "option-chain snapshot. "
                f"Pages={payload.get('pages_fetched', 1)}. "
                f"Truncated={payload.get('truncated', False)}."
            ),
    }

    quotes = []

    for item in results:
        details = (
            item.get(
                "details"
            )
            or {}
        )

        contract_type = (
            details.get(
                "contract_type"
            )
        )

        if contract_type == "call":
            right = "C"

        elif contract_type == "put":
            right = "P"

        else:
            continue

        strike = details.get(
            "strike_price"
        )

        expiration = details.get(
            "expiration_date"
        )

        if (
            strike is None
            or expiration is None
        ):
            continue

        last_quote = (
            item.get(
                "last_quote"
            )
            or {}
        )

        last_trade = (
            item.get(
                "last_trade"
            )
            or {}
        )

        greeks = (
            item.get(
                "greeks"
            )
            or {}
        )

        day = (
            item.get(
                "day"
            )
            or {}
        )

        quote_at = (
            _nanoseconds_to_iso(
                last_quote.get(
                    "last_updated"
                )
            )
        )

        trade_at = (
            _nanoseconds_to_iso(
                last_trade.get(
                    "sip_timestamp"
                )
            )
        )

        bid, bid_source = (
            _value_and_source(
                last_quote.get(
                    "bid"
                )
            )
        )

        ask, ask_source = (
            _value_and_source(
                last_quote.get(
                    "ask"
                )
            )
        )

        last, last_source = (
            _value_and_source(
                last_trade.get(
                    "price"
                )
            )
        )

        iv, iv_source = (
            _value_and_source(
                item.get(
                    "implied_volatility"
                )
            )
        )

        delta, delta_source = (
            _value_and_source(
                greeks.get(
                    "delta"
                )
            )
        )

        gamma, gamma_source = (
            _value_and_source(
                greeks.get(
                    "gamma"
                )
            )
        )

        theta, theta_source = (
            _value_and_source(
                greeks.get(
                    "theta"
                )
            )
        )

        vega, vega_source = (
            _value_and_source(
                greeks.get(
                    "vega"
                )
            )
        )

        volume, volume_source = (
            _value_and_source(
                day.get(
                    "volume"
                )
            )
        )

        (
            open_interest,
            open_interest_source,
        ) = _value_and_source(
            item.get(
                "open_interest"
            )
        )

        quote = {
            "provider_contract_id":
                details.get(
                    "ticker"
                ),

            "option_symbol":
                details.get(
                    "ticker"
                ),

            "right":
                right,

            "strike":
                strike,

            "expiration":
                expiration,

            "quote_at":
                quote_at,

            "bid":
                bid,

            "bid_source":
                bid_source,

            "bid_at":
                quote_at,

            "ask":
                ask,

            "ask_source":
                ask_source,

            "ask_at":
                quote_at,

            "last":
                last,

            "last_source":
                last_source,

            "last_at":
                trade_at,

            "implied_volatility":
                iv,

            "iv_source":
                iv_source,

            "iv_at":
                quote_at,

            "delta":
                delta,

            "delta_source":
                delta_source,

            "delta_at":
                quote_at,

            "gamma":
                gamma,

            "gamma_source":
                gamma_source,

            "gamma_at":
                quote_at,

            "theta":
                theta,

            "theta_source":
                theta_source,

            "theta_at":
                quote_at,

            "vega":
                vega,

            "vega_source":
                vega_source,

            "vega_at":
                quote_at,

            "volume":
                volume,

            "volume_source":
                volume_source,

            "volume_at":
                captured_at,

            "open_interest":
                open_interest,

            "open_interest_source":
                open_interest_source,

            "open_interest_at":
                captured_at,
        }

        quotes.append(
            quote
        )

    return (
        snapshot,
        quotes,
    )