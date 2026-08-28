from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from enum import Enum
from typing import Any


SAXO_LIVE_BASE_URL = (
    "https://gateway.saxobank.com/openapi"
)

SAXO_SIM_BASE_URL = (
    "https://gateway.saxobank.com/sim/openapi"
)


class SaxoError(RuntimeError):
    pass


class QuoteQuality(str, Enum):
    EXECUTABLE = "EXECUTABLE"
    DELAYED = "DELAYED"
    INDICATIVE = "INDICATIVE"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class SaxoOptionContract:
    uic: int
    option_root_id: int
    underlying_uic: int | None
    underlying: str
    put_call: str
    strike: float
    expiration: str
    trading_status: str | None
    contract_size: float | None = None


@dataclass(frozen=True)
class SaxoOptionQuote:
    uic: int
    bid: float | None
    ask: float | None
    mid: float | None
    bid_size: float | None
    ask_size: float | None
    delayed_by_minutes: int | None
    market_state: str | None
    price_source: str | None
    price_source_type: str | None
    price_type_bid: str | None
    price_type_ask: str | None
    last_updated: str | None

    @property
    def spread(self) -> float | None:
        if (
            self.bid is None
            or self.ask is None
        ):
            return None

        return self.ask - self.bid

    @property
    def computed_mid(
        self,
    ) -> float | None:
        if (
            self.bid is None
            or self.ask is None
        ):
            return None

        return (
            self.bid + self.ask
        ) / 2

    @property
    def spread_pct_mid(
        self,
    ) -> float | None:
        mid = self.computed_mid

        if (
            mid is None
            or mid == 0
        ):
            return None

        return (
            self.ask - self.bid
        ) / mid

    @property
    def is_stale(
        self,
    ) -> bool:
        return _is_provider_stale(
            self.price_type_bid,
            self.price_type_ask,
        )

    @property
    def is_indicative(
        self,
    ) -> bool:
        return _is_indicative(
            price_source_type=(
                self.price_source_type
            ),
            price_type_bid=(
                self.price_type_bid
            ),
            price_type_ask=(
                self.price_type_ask
            ),
        )

    @property
    def is_delayed(
        self,
    ) -> bool:
        return (
            self.delayed_by_minutes
            is not None
            and self.delayed_by_minutes > 0
        )

    @property
    def is_locked(
        self,
    ) -> bool:
        return (
            self.bid is not None
            and self.ask is not None
            and self.bid == self.ask
        )

    @property
    def is_crossed(
        self,
    ) -> bool:
        return (
            self.bid is not None
            and self.ask is not None
            and self.bid > self.ask
        )

    @property
    def is_stale(
        self,
    ) -> bool:
        return _is_provider_stale(
            self.price_type_bid,
            self.price_type_ask,
        )

    @property
    def is_indicative(
        self,
    ) -> bool:
        return _is_indicative(
            price_source_type=(
                self.price_source_type
            ),
            price_type_bid=(
                self.price_type_bid
            ),
            price_type_ask=(
                self.price_type_ask
            ),
        )

    @property
    def is_delayed(
        self,
    ) -> bool:
        return (
            self.delayed_by_minutes
            is not None
            and self.delayed_by_minutes > 0
        )

    @property
    def is_locked(
        self,
    ) -> bool:
        return (
            self.bid is not None
            and self.ask is not None
            and self.bid == self.ask
        )

    @property
    def is_crossed(
        self,
    ) -> bool:
        return (
            self.bid is not None
            and self.ask is not None
            and self.bid > self.ask
        )

    @property
    def quality(
        self,
    ) -> QuoteQuality:
        return _classify_quote_quality(
            bid=self.bid,
            ask=self.ask,
            bid_size=self.bid_size,
            ask_size=self.ask_size,
            delayed_by_minutes=(
                self.delayed_by_minutes
            ),
            market_state=(
                self.market_state
            ),
            price_source_type=(
                self.price_source_type
            ),
            price_type_bid=(
                self.price_type_bid
            ),
            price_type_ask=(
                self.price_type_ask
            ),
        )

    @property
    def is_executable(
        self,
    ) -> bool:
        return (
            self.quality
            == QuoteQuality.EXECUTABLE
        )


@dataclass(frozen=True)
class SaxoUnderlyingQuote:
    """
    Separate observation of the underlying.

    This must not be flattened into a Massive
    option snapshot because it comes from a
    different provider and observation time.
    """

    uic: int
    asset_type: str

    bid: float | None
    ask: float | None
    mid: float | None

    bid_size: float | None
    ask_size: float | None

    delayed_by_minutes: int | None

    market_state: str | None

    price_source: str | None
    price_source_type: str | None

    price_type_bid: str | None
    price_type_ask: str | None

    last_updated: str | None

    @property
    def computed_mid(
        self,
    ) -> float | None:
        if (
            self.bid is None
            or self.ask is None
        ):
            return None

        return (
            self.bid + self.ask
        ) / 2

    @property
    def reference_price(
        self,
    ) -> float | None:
        """
        Prefer a midpoint calculated from bid/ask.

        Fall back to Saxo's reported Mid only
        when both sides are not available.
        """

        computed = self.computed_mid

        if computed is not None:
            return computed

        return self.mid

    @property
    def spread(
        self,
    ) -> float | None:
        if (
            self.bid is None
            or self.ask is None
        ):
            return None

        return self.ask - self.bid

    @property
    def is_stale(
        self,
    ) -> bool:
        return _is_provider_stale(
            self.price_type_bid,
            self.price_type_ask,
        )

    @property
    def is_indicative(
        self,
    ) -> bool:
        return _is_indicative(
            price_source_type=(
                self.price_source_type
            ),
            price_type_bid=(
                self.price_type_bid
            ),
            price_type_ask=(
                self.price_type_ask
            ),
        )

    @property
    def is_delayed(
        self,
    ) -> bool:
        return (
            self.delayed_by_minutes
            is not None
            and self.delayed_by_minutes > 0
        )

    @property
    def is_locked(
        self,
    ) -> bool:
        return (
            self.bid is not None
            and self.ask is not None
            and self.bid == self.ask
        )

    @property
    def is_crossed(
        self,
    ) -> bool:
        return (
            self.bid is not None
            and self.ask is not None
            and self.bid > self.ask
        )

    @property
    def quality(
        self,
    ) -> QuoteQuality:
        return _classify_quote_quality(
            bid=self.bid,
            ask=self.ask,
            bid_size=self.bid_size,
            ask_size=self.ask_size,
            delayed_by_minutes=(
                self.delayed_by_minutes
            ),
            market_state=(
                self.market_state
            ),
            price_source_type=(
                self.price_source_type
            ),
            price_type_bid=(
                self.price_type_bid
            ),
            price_type_ask=(
                self.price_type_ask
            ),
        )

    @property
    def is_executable(
        self,
    ) -> bool:
        return (
            self.quality
            == QuoteQuality.EXECUTABLE
        )


def _normalized_price_type(
    value: str | None,
) -> str:
    return (
        value or ""
    ).replace(
        " ",
        "",
    ).replace(
        "_",
        "",
    ).upper()


def _has_no_access(
    price_type_bid: str | None,
    price_type_ask: str | None,
) -> bool:
    return (
        _normalized_price_type(
            price_type_bid
        )
        == "NOACCESS"
        or _normalized_price_type(
            price_type_ask
        )
        == "NOACCESS"
    )


def _is_provider_stale(
    price_type_bid: str | None,
    price_type_ask: str | None,
) -> bool:
    return (
        "OLDINDICATIVE"
        in _normalized_price_type(
            price_type_bid
        )
        or
        "OLDINDICATIVE"
        in _normalized_price_type(
            price_type_ask
        )
    )


def _is_indicative(
    *,
    price_source_type: str | None,
    price_type_bid: str | None,
    price_type_ask: str | None,
) -> bool:
    source_type = (
        price_source_type or ""
    ).strip().upper()

    bid_type = (
        _normalized_price_type(
            price_type_bid
        )
    )

    ask_type = (
        _normalized_price_type(
            price_type_ask
        )
    )

    return (
        source_type != "FIRM"
        or "INDICATIVE" in bid_type
        or "INDICATIVE" in ask_type
    )


def _classify_quote_quality(
    *,
    bid: float | None,
    ask: float | None,
    bid_size: float | None,
    ask_size: float | None,
    delayed_by_minutes: int | None,
    market_state: str | None,
    price_source_type: str | None,
    price_type_bid: str | None,
    price_type_ask: str | None,
) -> QuoteQuality:

    if (
        bid is None
        or ask is None
    ):
        return QuoteQuality.UNAVAILABLE

    if (
        bid <= 0
        or ask <= 0
    ):
        return QuoteQuality.UNAVAILABLE

    if bid > ask:
        return QuoteQuality.UNAVAILABLE

    if _has_no_access(
        price_type_bid,
        price_type_ask,
    ):
        return QuoteQuality.UNAVAILABLE

    if _is_provider_stale(
        price_type_bid,
        price_type_ask,
    ):
        return QuoteQuality.STALE

    if _is_indicative(
        price_source_type=(
            price_source_type
        ),
        price_type_bid=(
            price_type_bid
        ),
        price_type_ask=(
            price_type_ask
        ),
    ):
        return QuoteQuality.INDICATIVE

    if (
        market_state or ""
    ).strip().upper() != "OPEN":
        return QuoteQuality.INDICATIVE

    if (
        bid_size is None
        or ask_size is None
    ):
        return QuoteQuality.INDICATIVE

    if (
        bid_size <= 0
        or ask_size <= 0
    ):
        return QuoteQuality.INDICATIVE

    if (
        delayed_by_minutes is not None
        and delayed_by_minutes > 0
    ):
        return QuoteQuality.DELAYED

    return QuoteQuality.EXECUTABLE


class SaxoClient:
    """
    Minimal read-only Saxo OpenAPI client
    for Christiania.

    Exposed functionality:
      - instrument / option-root search
      - option-space lookup
      - option info-price retrieval
      - underlying stock info-price retrieval

    It deliberately contains no order-placement
    functionality.
    """

    def __init__(
        self,
        access_token: str,
        base_url: str = SAXO_LIVE_BASE_URL,
        timeout_seconds: int = 30,
    ):
        if not access_token:
            raise ValueError(
                "Saxo access token is required."
            )

        self.access_token = access_token
        self.base_url = (
            base_url.rstrip("/")
        )
        self.timeout_seconds = (
            timeout_seconds
        )

    def _get_json(
        self,
        path: str,
        params:
            dict[str, Any] | None = None,
    ) -> dict[str, Any]:

        url = (
            f"{self.base_url}{path}"
        )

        if params:
            clean_params = {
                key: value
                for key, value
                in params.items()
                if value is not None
            }

            query = (
                urllib.parse.urlencode(
                    clean_params
                )
            )

            if query:
                url = (
                    f"{url}?{query}"
                )

        request = urllib.request.Request(
            url,
            method="GET",
            headers={
                "Authorization":
                    f"Bearer "
                    f"{self.access_token}",

                "Accept":
                    "application/json",
            },
        )

        try:
            with (
                urllib.request.urlopen(
                    request,
                    timeout=(
                        self.timeout_seconds
                    ),
                )
            ) as response:
                return json.loads(
                    response
                    .read()
                    .decode("utf-8")
                )

        except (
            urllib.error.HTTPError
        ) as exc:
            body = (
                exc.read()
                .decode(
                    "utf-8",
                    errors="replace",
                )
            )

            raise SaxoError(
                f"Saxo HTTP "
                f"{exc.code}: {body}"
            ) from exc

        except (
            urllib.error.URLError
        ) as exc:
            raise SaxoError(
                "Could not reach Saxo "
                f"OpenAPI: {exc}"
            ) from exc

    def search_option_roots(
        self,
        keywords: str,
        include_non_tradable:
            bool = True,
    ) -> list[dict[str, Any]]:

        payload = self._get_json(
            "/ref/v1/instruments",
            {
                "Keywords":
                    keywords,

                "AssetTypes":
                    "StockOption",

                "IncludeNonTradable":
                    str(
                        include_non_tradable
                    ).lower(),
            },
        )

        results = (
            payload.get(
                "Data",
                [],
            )
        )

        return [
            item
            for item in results
            if (
                item.get(
                    "SummaryType"
                )
                == "ContractOptionRoot"
                and item.get(
                    "ExchangeId"
                )
                == "OPRA"
            )
        ]

    def find_option_root(
        self,
        underlying: str,
    ) -> dict[str, Any]:

        roots = (
            self.search_option_roots(
                underlying
            )
        )

        if not roots:
            raise SaxoError(
                "No Saxo OPRA "
                "stock-option root found "
                f"for {underlying}."
            )

        exact_symbol_matches = [
            item
            for item in roots
            if str(
                item.get(
                    "Symbol",
                    "",
                )
            )
            .upper()
            .startswith(
                f"{underlying.upper()}:"
            )
        ]

        if (
            len(
                exact_symbol_matches
            )
            == 1
        ):
            return (
                exact_symbol_matches[0]
            )

        if (
            len(
                exact_symbol_matches
            )
            > 1
        ):
            raise SaxoError(
                "Multiple exact OPRA "
                "option roots found for "
                f"{underlying}."
            )

        if len(roots) == 1:
            return roots[0]

        raise SaxoError(
            "Multiple OPRA option roots "
            f"found for {underlying}; "
            "could not select one safely."
        )

    def get_option_space(
        self,
        option_root_id: int,
        expiration:
            str | None = None,
    ) -> dict[str, Any]:

        params: dict[
            str,
            Any,
        ] = {}

        if expiration:
            params[
                "OptionSpaceSegment"
            ] = "SpecificDates"

            params[
                "ExpiryDates"
            ] = expiration

        else:
            params[
                "OptionSpaceSegment"
            ] = "AllDates"

        return self._get_json(
            "/ref/v1/instruments/"
            "contractoptionspaces/"
            f"{option_root_id}",
            params,
        )

    @staticmethod
    def _normalise_expiration(
        value: str,
    ) -> str:
        return value[:10]

    def find_option_contract(
        self,
        underlying: str,
        expiration: str,
        strike: float,
        put_call: str,
    ) -> SaxoOptionContract:

        root = (
            self.find_option_root(
                underlying
            )
        )

        option_root_id = int(
            root["Identifier"]
        )

        space = self.get_option_space(
            option_root_id=(
                option_root_id
            ),
            expiration=expiration,
        )

        target_expiration = (
            self._normalise_expiration(
                expiration
            )
        )

        target_put_call = (
            put_call
            .strip()
            .lower()
        )

        target_strike = float(
            strike
        )

        contract_size = (
            _optional_float(
                space.get(
                    "ContractSize"
                )
            )
        )

        matches: list[
            SaxoOptionContract
        ] = []

        for expiry_entry in (
            space.get(
                "OptionSpace",
                [],
            )
        ):
            expiry_value = (
                expiry_entry.get(
                    "Expiry"
                )
            )

            if not expiry_value:
                continue

            expiry_date = (
                self._normalise_expiration(
                    str(
                        expiry_value
                    )
                )
            )

            if (
                expiry_date
                != target_expiration
            ):
                continue

            for option in (
                expiry_entry.get(
                    "SpecificOptions",
                    [],
                )
            ):
                option_put_call = (
                    str(
                        option.get(
                            "PutCall",
                            "",
                        )
                    ).lower()
                )

                option_strike = (
                    option.get(
                        "StrikePrice"
                    )
                )

                if option_strike is None:
                    continue

                if (
                    option_put_call
                    != target_put_call
                ):
                    continue

                if abs(
                    float(option_strike)
                    - target_strike
                ) > 0.000001:
                    continue

                uic = option.get(
                    "Uic"
                )

                if uic is None:
                    continue

                underlying_uic = (
                    option.get(
                        "UnderlyingUic"
                    )
                )

                matches.append(
                    SaxoOptionContract(
                        uic=int(uic),

                        option_root_id=(
                            option_root_id
                        ),

                        underlying_uic=(
                            int(
                                underlying_uic
                            )
                            if (
                                underlying_uic
                                is not None
                            )
                            else None
                        ),

                        underlying=(
                            underlying.upper()
                        ),

                        put_call=str(
                            option.get(
                                "PutCall",
                                "",
                            )
                        ),

                        strike=float(
                            option_strike
                        ),

                        expiration=(
                            expiry_date
                        ),

                        trading_status=(
                            option.get(
                                "TradingStatus"
                            )
                        ),

                        contract_size=(
                            contract_size
                        ),
                    )
                )

        if not matches:
            raise SaxoError(
                "No Saxo option contract "
                "matched "
                f"{underlying.upper()} "
                f"{target_expiration} "
                f"{put_call} "
                f"{target_strike:g}."
            )

        if len(matches) > 1:
            raise SaxoError(
                "Multiple Saxo contracts "
                "matched "
                f"{underlying.upper()} "
                f"{target_expiration} "
                f"{put_call} "
                f"{target_strike:g}."
            )

        return matches[0]

    def get_option_quote(
        self,
        uic: int,
    ) -> SaxoOptionQuote:

        payload = self._get_json(
            "/trade/v1/infoprices",
            {
                "Uic":
                    uic,

                "AssetType":
                    "StockOption",

                "FieldGroups":
                    "Quote",
            },
        )

        quote = (
            payload.get(
                "Quote"
            )
            or {}
        )

        return SaxoOptionQuote(
            uic=int(
                payload.get(
                    "Uic",
                    uic,
                )
            ),

            bid=_optional_float(
                quote.get(
                    "Bid"
                )
            ),

            ask=_optional_float(
                quote.get(
                    "Ask"
                )
            ),

            mid=_optional_float(
                quote.get(
                    "Mid"
                )
            ),

            bid_size=_optional_float(
                quote.get(
                    "BidSize"
                )
            ),

            ask_size=_optional_float(
                quote.get(
                    "AskSize"
                )
            ),

            delayed_by_minutes=(
                _optional_int(
                    quote.get(
                        "DelayedByMinutes"
                    )
                )
            ),

            market_state=(
                quote.get(
                    "MarketState"
                )
            ),

            price_source=(
                quote.get(
                    "PriceSource"
                )
                or payload.get(
                    "PriceSource"
                )
            ),

            price_source_type=(
                quote.get(
                    "PriceSourceType"
                )
            ),

            price_type_bid=(
                quote.get(
                    "PriceTypeBid"
                )
            ),

            price_type_ask=(
                quote.get(
                    "PriceTypeAsk"
                )
            ),

            last_updated=(
                payload.get(
                    "LastUpdated"
                )
            ),
        )

    def get_underlying_quote(
        self,
        uic: int,
        asset_type: str = "Stock",
    ) -> SaxoUnderlyingQuote:
        """
        Fetch the underlying instrument as its
        own Saxo observation.

        The returned quote retains Saxo's own
        timestamp and quote-quality metadata.
        """

        payload = self._get_json(
            "/trade/v1/infoprices",
            {
                "Uic":
                    uic,

                "AssetType":
                    asset_type,

                "FieldGroups":
                    "Quote",
            },
        )

        quote = (
            payload.get(
                "Quote"
            )
            or {}
        )

        return SaxoUnderlyingQuote(
            uic=int(
                payload.get(
                    "Uic",
                    uic,
                )
            ),

            asset_type=str(
                payload.get(
                    "AssetType",
                    asset_type,
                )
            ),

            bid=_optional_float(
                quote.get(
                    "Bid"
                )
            ),

            ask=_optional_float(
                quote.get(
                    "Ask"
                )
            ),

            mid=_optional_float(
                quote.get(
                    "Mid"
                )
            ),

            bid_size=_optional_float(
                quote.get(
                    "BidSize"
                )
            ),

            ask_size=_optional_float(
                quote.get(
                    "AskSize"
                )
            ),

            delayed_by_minutes=(
                _optional_int(
                    quote.get(
                        "DelayedByMinutes"
                    )
                )
            ),

            market_state=(
                quote.get(
                    "MarketState"
                )
            ),

            price_source=(
                quote.get(
                    "PriceSource"
                )
                or payload.get(
                    "PriceSource"
                )
            ),

            price_source_type=(
                quote.get(
                    "PriceSourceType"
                )
            ),

            price_type_bid=(
                quote.get(
                    "PriceTypeBid"
                )
            ),

            price_type_ask=(
                quote.get(
                    "PriceTypeAsk"
                )
            ),

            last_updated=(
                payload.get(
                    "LastUpdated"
                )
            ),
        )

    def get_option_contract_and_quote(
        self,
        underlying: str,
        expiration: str,
        strike: float,
        put_call: str,
    ) -> tuple[
        SaxoOptionContract,
        SaxoOptionQuote,
    ]:

        contract = (
            self.find_option_contract(
                underlying=underlying,
                expiration=expiration,
                strike=strike,
                put_call=put_call,
            )
        )

        quote = (
            self.get_option_quote(
                contract.uic
            )
        )

        return (
            contract,
            quote,
        )

    def get_option_underlying_quote(
        self,
        contract:
            SaxoOptionContract,
    ) -> SaxoUnderlyingQuote:
        """
        Resolve an underlying observation directly
        from an already-resolved option contract.
        """

        if (
            contract.underlying_uic
            is None
        ):
            raise SaxoError(
                "Resolved Saxo option contract "
                "has no underlying UIC."
            )

        return self.get_underlying_quote(
            uic=(
                contract.underlying_uic
            ),
            asset_type="Stock",
        )


def _optional_float(
    value: Any,
) -> float | None:
    if value is None:
        return None

    return float(value)


def _optional_int(
    value: Any,
) -> int | None:
    if value is None:
        return None

    return int(value)
