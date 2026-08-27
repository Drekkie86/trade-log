from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


SAXO_LIVE_BASE_URL = "https://gateway.saxobank.com/openapi"
SAXO_SIM_BASE_URL = "https://gateway.saxobank.com/sim/openapi"


class SaxoError(RuntimeError):
    pass


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
        if self.bid is None or self.ask is None:
            return None
        return self.ask - self.bid

    @property
    def spread_pct_mid(self) -> float | None:
        if self.bid is None or self.ask is None:
            return None

        mid = self.mid
        if mid is None:
            mid = (self.bid + self.ask) / 2

        if mid == 0:
            return None

        return (self.ask - self.bid) / mid


class SaxoClient:
    """
    Minimal read-only Saxo OpenAPI client for Christiania.

    This client deliberately exposes only:
      - instrument / option-root search
      - contract option space lookup
      - info-price retrieval

    It contains no order-placement functionality.
    """

    def __init__(
        self,
        access_token: str,
        base_url: str = SAXO_LIVE_BASE_URL,
        timeout_seconds: int = 30,
    ):
        if not access_token:
            raise ValueError("Saxo access token is required.")

        self.access_token = access_token
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def _get_json(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}{path}"

        if params:
            clean_params = {
                key: value
                for key, value in params.items()
                if value is not None
            }
            query = urllib.parse.urlencode(clean_params)
            if query:
                url = f"{url}?{query}"

        request = urllib.request.Request(
            url,
            method="GET",
            headers={
                "Authorization": f"Bearer {self.access_token}",
                "Accept": "application/json",
            },
        )

        try:
            with urllib.request.urlopen(
                request,
                timeout=self.timeout_seconds,
            ) as response:
                return json.loads(response.read().decode("utf-8"))

        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise SaxoError(
                f"Saxo HTTP {exc.code}: {body}"
            ) from exc

        except urllib.error.URLError as exc:
            raise SaxoError(
                f"Could not reach Saxo OpenAPI: {exc}"
            ) from exc

    def search_option_roots(
        self,
        keywords: str,
        include_non_tradable: bool = True,
    ) -> list[dict[str, Any]]:
        payload = self._get_json(
            "/ref/v1/instruments",
            {
                "Keywords": keywords,
                "AssetTypes": "StockOption",
                "IncludeNonTradable": str(
                    include_non_tradable
                ).lower(),
            },
        )

        results = payload.get("Data", [])

        return [
            item
            for item in results
            if item.get("SummaryType") == "ContractOptionRoot"
        ]

    def find_option_root(
        self,
        underlying: str,
    ) -> dict[str, Any]:
        roots = self.search_option_roots(underlying)

        if not roots:
            raise SaxoError(
                f"No Saxo stock-option root found for {underlying}."
            )

        exact_symbol_matches = [
            item
            for item in roots
            if str(item.get("Symbol", ""))
            .upper()
            .startswith(f"{underlying.upper()}:")
        ]

        if len(exact_symbol_matches) == 1:
            return exact_symbol_matches[0]

        if len(exact_symbol_matches) > 1:
            raise SaxoError(
                f"Multiple exact option roots found for {underlying}."
            )

        if len(roots) == 1:
            return roots[0]

        raise SaxoError(
            f"Multiple option roots found for {underlying}; "
            "could not select one safely."
        )

    def get_option_space(
        self,
        option_root_id: int,
        expiration: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {}

        if expiration:
            params["OptionSpaceSegment"] = "SpecificDates"
            params["ExpiryDates"] = expiration
        else:
            params["OptionSpaceSegment"] = "AllDates"

        return self._get_json(
            f"/ref/v1/instruments/contractoptionspaces/"
            f"{option_root_id}",
            params,
        )

    @staticmethod
    def _normalise_expiration(value: str) -> str:
        return value[:10]

    def find_option_contract(
        self,
        underlying: str,
        expiration: str,
        strike: float,
        put_call: str,
    ) -> SaxoOptionContract:
        root = self.find_option_root(underlying)

        option_root_id = int(root["Identifier"])

        space = self.get_option_space(
            option_root_id=option_root_id,
            expiration=expiration,
        )

        target_expiration = self._normalise_expiration(expiration)
        target_put_call = put_call.strip().lower()
        target_strike = float(strike)

        matches: list[SaxoOptionContract] = []

        for expiry_entry in space.get("OptionSpace", []):
            expiry_value = expiry_entry.get("Expiry")

            if not expiry_value:
                continue

            expiry_date = self._normalise_expiration(
                str(expiry_value)
            )

            if expiry_date != target_expiration:
                continue

            for option in expiry_entry.get(
                "SpecificOptions", []
            ):
                option_put_call = str(
                    option.get("PutCall", "")
                ).lower()

                option_strike = option.get("StrikePrice")

                if option_strike is None:
                    continue

                if option_put_call != target_put_call:
                    continue

                if abs(
                    float(option_strike) - target_strike
                ) > 0.000001:
                    continue

                uic = option.get("Uic")

                if uic is None:
                    continue

                matches.append(
                    SaxoOptionContract(
                        uic=int(uic),
                        option_root_id=option_root_id,
                        underlying_uic=(
                            int(option["UnderlyingUic"])
                            if option.get("UnderlyingUic")
                            is not None
                            else None
                        ),
                        underlying=underlying.upper(),
                        put_call=str(
                            option.get("PutCall", "")
                        ),
                        strike=float(option_strike),
                        expiration=expiry_date,
                        trading_status=option.get(
                            "TradingStatus"
                        ),
                    )
                )

        if not matches:
            raise SaxoError(
                "No Saxo option contract matched "
                f"{underlying.upper()} "
                f"{target_expiration} "
                f"{put_call} {target_strike:g}."
            )

        if len(matches) > 1:
            raise SaxoError(
                "Multiple Saxo contracts matched "
                f"{underlying.upper()} "
                f"{target_expiration} "
                f"{put_call} {target_strike:g}."
            )

        return matches[0]

    def get_option_quote(
        self,
        uic: int,
    ) -> SaxoOptionQuote:
        payload = self._get_json(
            "/trade/v1/infoprices",
            {
                "Uic": uic,
                "AssetType": "StockOption",
                "FieldGroups": "Quote",
            },
        )

        quote = payload.get("Quote") or {}

        return SaxoOptionQuote(
            uic=int(payload.get("Uic", uic)),
            bid=_optional_float(quote.get("Bid")),
            ask=_optional_float(quote.get("Ask")),
            mid=_optional_float(quote.get("Mid")),
            bid_size=_optional_float(
                quote.get("BidSize")
            ),
            ask_size=_optional_float(
                quote.get("AskSize")
            ),
            delayed_by_minutes=_optional_int(
                quote.get("DelayedByMinutes")
            ),
            market_state=quote.get("MarketState"),
            price_source=(
                quote.get("PriceSource")
                or payload.get("PriceSource")
            ),
            price_source_type=quote.get(
                "PriceSourceType"
            ),
            price_type_bid=quote.get(
                "PriceTypeBid"
            ),
            price_type_ask=quote.get(
                "PriceTypeAsk"
            ),
            last_updated=payload.get("LastUpdated"),
        )

    def get_option_contract_and_quote(
        self,
        underlying: str,
        expiration: str,
        strike: float,
        put_call: str,
    ) -> tuple[SaxoOptionContract, SaxoOptionQuote]:
        contract = self.find_option_contract(
            underlying=underlying,
            expiration=expiration,
            strike=strike,
            put_call=put_call,
        )

        quote = self.get_option_quote(contract.uic)

        return contract, quote


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)