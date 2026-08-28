from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import (
    date,
    datetime,
    timedelta,
    timezone,
)
from json import JSONDecodeError
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import (
    urlencode,
    urlparse,
)
from urllib.request import (
    Request,
    urlopen,
)
from zoneinfo import ZoneInfo


MASSIVE_BASE_URL = "https://api.massive.com"

PROVENANCE_FETCHED = "FETCHED"
PROVENANCE_UNKNOWN = "UNKNOWN"

US_EASTERN = ZoneInfo(
    "America/New_York"
)


class MassiveError(RuntimeError):
    pass


class MassiveAuthenticationError(
    MassiveError
):
    pass


class MassiveRateLimitError(
    MassiveError
):
    pass


class MassiveResponseError(
    MassiveError
):
    pass


class MassiveNetworkError(
    MassiveError
):
    pass


class MassiveUnsafeUrlError(
    MassiveError
):
    pass


class MassiveTruncatedError(
    MassiveError
):
    pass


@dataclass(frozen=True)
class MassiveClient:
    api_key: str = field(
        repr=False
    )

    base_url: str = MASSIVE_BASE_URL
    timeout_seconds: int = 30

    max_retries: int = 3
    retry_base_seconds: float = 1.0
    retry_max_seconds: float = 8.0

    def __post_init__(self):
        if not self.api_key:
            raise ValueError(
                "Massive API key is required."
            )

        if self.timeout_seconds <= 0:
            raise ValueError(
                "timeout_seconds must be positive."
            )

        if self.max_retries < 0:
            raise ValueError(
                "max_retries cannot be negative."
            )

        self._validate_url(
            self.base_url
        )

    def _validate_url(
        self,
        url: str,
    ) -> None:
        base = urlparse(
            self.base_url
        )

        target = urlparse(url)

        if (
            target.scheme != base.scheme
            or target.netloc != base.netloc
        ):
            raise MassiveUnsafeUrlError(
                "Refusing to send Massive "
                "credentials to unexpected URL: "
                f"{target.scheme}://"
                f"{target.netloc}"
            )

    def _retry_delay(
        self,
        attempt: int,
        retry_after: str | None,
    ) -> float:
        if retry_after:
            try:
                parsed = float(
                    retry_after
                )

                if parsed >= 0:
                    return min(
                        parsed,
                        self.retry_max_seconds,
                    )

            except ValueError:
                pass

        return min(
            self.retry_base_seconds
            * (2 ** attempt),
            self.retry_max_seconds,
        )

    def _get_json_url(
        self,
        url: str,
    ) -> dict[str, Any]:
        self._validate_url(url)

        attempt = 0

        while True:
            request = Request(
                url,
                headers={
                    "Authorization":
                        f"Bearer "
                        f"{self.api_key}",

                    "Accept":
                        "application/json",

                    "User-Agent":
                        "Christiania/0.1",
                },
                method="GET",
            )

            try:
                with urlopen(
                    request,
                    timeout=self.timeout_seconds,
                ) as response:
                    raw = (
                        response
                        .read()
                        .decode("utf-8")
                    )

                try:
                    payload = json.loads(
                        raw
                    )

                except JSONDecodeError as exc:
                    raise MassiveResponseError(
                        "Massive returned "
                        "malformed JSON."
                    ) from exc

                if not isinstance(
                    payload,
                    dict,
                ):
                    raise MassiveResponseError(
                        "Massive returned an "
                        "unexpected JSON structure."
                    )

                return payload

            except HTTPError as exc:
                status = exc.code

                body = (
                    exc.read()
                    .decode(
                        "utf-8",
                        errors="replace",
                    )
                )

                if status in {
                    401,
                    403,
                }:
                    raise (
                        MassiveAuthenticationError(
                            "Massive authentication "
                            f"failed with HTTP "
                            f"{status}."
                        )
                    ) from exc

                retryable = (
                    status == 429
                    or 500 <= status <= 599
                )

                if retryable:
                    if (
                        attempt
                        >= self.max_retries
                    ):
                        if status == 429:
                            raise (
                                MassiveRateLimitError(
                                    "Massive rate limit "
                                    "persisted after "
                                    "retries."
                                )
                            ) from exc

                        raise MassiveResponseError(
                            "Massive server error "
                            f"HTTP {status} persisted "
                            "after retries."
                        ) from exc

                    delay = self._retry_delay(
                        attempt,
                        exc.headers.get(
                            "Retry-After"
                        ),
                    )

                    time.sleep(delay)

                    attempt += 1
                    continue

                raise MassiveResponseError(
                    "Massive request failed "
                    f"with HTTP {status}: "
                    f"{body[:500]}"
                ) from exc

            except URLError as exc:
                if (
                    attempt
                    >= self.max_retries
                ):
                    raise MassiveNetworkError(
                        "Could not reach Massive "
                        "after retries."
                    ) from exc

                delay = self._retry_delay(
                    attempt,
                    None,
                )

                time.sleep(delay)

                attempt += 1

    def _get_json(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        params = params or {}

        query = urlencode(
            {
                key: value
                for key, value
                in params.items()
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
        expiration_date_gte:
            str | None = None,
        expiration_date_lte:
            str | None = None,
        contract_type:
            str | None = None,
    ) -> dict[str, Any]:
        symbol = (
            underlying
            .strip()
            .upper()
        )

        if not symbol:
            raise ValueError(
                "Underlying cannot be blank."
            )

        if (
            limit < 1
            or limit > 250
        ):
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
            f"/v3/snapshot/options/"
            f"{symbol}",
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
        contract_type:
            str | None = None,
        page_limit: int = 250,
        max_pages: int = 20,
        as_of_date:
            date | None = None,
        require_complete:
            bool = False,
    ) -> dict[str, Any]:
        """
        Fetch a paginated option-chain window.

        Default DTE calculations use the US
        Eastern calendar date.

        If require_complete=True, Christiania
        refuses to return a truncated research
        universe.
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

        if (
            page_limit < 1
            or page_limit > 250
        ):
            raise ValueError(
                "Massive option-chain page limit "
                "must be between 1 and 250."
            )

        reference_date = (
            as_of_date
            or datetime.now(
                US_EASTERN
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

        first_page = (
            self.get_option_chain_page(
                underlying,
                limit=page_limit,
                order="asc",
                sort="ticker",
                expiration_date_gte=
                    expiration_gte,
                expiration_date_lte=
                    expiration_lte,
                contract_type=
                    contract_type,
            )
        )

        combined_results = list(
            first_page.get(
                "results"
            )
            or []
        )

        request_ids: list[str] = []

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
            and pages_fetched
            < max_pages
        ):
            page = (
                self._get_json_url(
                    next_url
                )
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

        truncated = bool(
            next_url
        )

        if (
            require_complete
            and truncated
        ):
            raise MassiveTruncatedError(
                "Massive option-chain research "
                "universe was truncated after "
                f"{pages_fetched} pages."
            )

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

            "reference_date":
                reference_date.isoformat(),

            "reference_timezone":
                "America/New_York",

            "truncated":
                truncated,
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
    Christiania's normalized research form.

    Missing values remain None + UNKNOWN.

    No database writes happen here.
    """

    symbol = (
        underlying
        .strip()
        .upper()
    )

    if not symbol:
        raise ValueError(
            "Underlying cannot be blank."
        )

    results = (
        payload.get(
            "results"
        )
        or []
    )

    captured_at = _iso_now()

    underlying_candidates = []

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

        if price is None:
            continue

        observed_at = (
            _nanoseconds_to_iso(
                underlying_asset.get(
                    "last_updated"
                )
            )
        )

        underlying_candidates.append(
            (
                price,
                observed_at,
            )
        )

    underlying_price = None
    underlying_at = None

    if underlying_candidates:
        timestamped = [
            candidate
            for candidate
            in underlying_candidates
            if candidate[1]
            is not None
        ]

        if timestamped:
            (
                underlying_price,
                underlying_at,
            ) = max(
                timestamped,
                key=lambda item:
                    item[1],
            )

        else:
            (
                underlying_price,
                underlying_at,
            ) = (
                underlying_candidates[0]
            )

    (
        normalized_underlying_price,
        underlying_source,
    ) = _value_and_source(
        underlying_price
    )

    request_ids = (
        payload.get(
            "request_ids"
        )
        or []
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
            PROVENANCE_UNKNOWN,

        "fx_at":
            None,

        "notes":
            (
                "Normalized from Massive "
                "option-chain snapshot. "
                f"Pages="
                f"{payload.get('pages_fetched', 1)}. "
                f"Truncated="
                f"{payload.get('truncated', False)}. "
                f"RequestIds="
                f"{','.join(request_ids)}."
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

            "shares_per_contract":
                details.get(
                    "shares_per_contract"
                ),

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

            # Massive did not provide a
            # dedicated model-observation
            # timestamp in the Starter
            # payload we inspected.
            "iv_at":
                None,

            "delta":
                delta,

            "delta_source":
                delta_source,

            "delta_at":
                None,

            "gamma":
                gamma,

            "gamma_source":
                gamma_source,

            "gamma_at":
                None,

            "theta":
                theta,

            "theta_source":
                theta_source,

            "theta_at":
                None,

            "vega":
                vega,

            "vega_source":
                vega_source,

            "vega_at":
                None,

            "volume":
                volume,

            "volume_source":
                volume_source,

            # Retrieval time is not the
            # market observation time.
            "volume_at":
                None,

            "open_interest":
                open_interest,

            "open_interest_source":
                open_interest_source,

            # OI is daily data; do not
            # pretend captured_at is its
            # observation timestamp.
            "open_interest_at":
                None,
        }

        quotes.append(
            quote
        )

    return (
        snapshot,
        quotes,
    )