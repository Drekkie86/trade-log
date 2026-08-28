from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.providers.saxo import (
    SaxoClient,
    SaxoOptionContract,
    SaxoOptionQuote,
)


class OptionBridgeError(RuntimeError):
    pass


class ContractIdentityError(
    OptionBridgeError
):
    pass


@dataclass(frozen=True)
class BridgedOptionQuote:
    underlying: str
    expiration: str
    strike: float
    right: str

    massive_symbol: str | None
    massive_bid: float | None
    massive_ask: float | None
    massive_iv: float | None
    massive_delta: float | None
    massive_open_interest: float | None
    massive_shares_per_contract: float | None

    saxo_contract: SaxoOptionContract
    saxo_quote: SaxoOptionQuote

    @property
    def saxo_bid(self) -> float | None:
        return self.saxo_quote.bid

    @property
    def saxo_ask(self) -> float | None:
        return self.saxo_quote.ask

    @property
    def saxo_mid(self) -> float | None:
        return self.saxo_quote.mid

    @property
    def saxo_spread(self) -> float | None:
        return self.saxo_quote.spread

    @property
    def saxo_spread_pct_mid(self) -> float | None:
        return self.saxo_quote.spread_pct_mid

    @property
    def quote_quality(self):
        return self.saxo_quote.quality

    @property
    def is_executable(self) -> bool:
        return self.saxo_quote.is_executable


def _normalize_right(value: Any) -> str:
    if value is None:
        raise OptionBridgeError(
            "Option right is missing."
        )

    normalized = (
        str(value)
        .strip()
        .upper()
    )

    if normalized in {
        "C",
        "CALL",
    }:
        return "Call"

    if normalized in {
        "P",
        "PUT",
    }:
        return "Put"

    raise OptionBridgeError(
        f"Unsupported option right: "
        f"{value!r}"
    )


def _required_value(
    quote: dict[str, Any],
    key: str,
) -> Any:
    value = quote.get(key)

    if value is None:
        raise OptionBridgeError(
            "Massive quote is missing "
            f"required field: {key}"
        )

    return value


def _optional_float(
    value: Any,
) -> float | None:
    if value is None:
        return None

    return float(value)


def _validate_contract_identity(
    *,
    massive_shares_per_contract:
        float | None,
    saxo_contract_size:
        float | None,
) -> None:

    if massive_shares_per_contract is None:
        raise ContractIdentityError(
            "Massive contract multiplier "
            "is missing."
        )

    if saxo_contract_size is None:
        raise ContractIdentityError(
            "Saxo contract multiplier "
            "is missing."
        )

    if abs(
        massive_shares_per_contract
        - saxo_contract_size
    ) > 0.000001:
        raise ContractIdentityError(
            "Contract multiplier mismatch: "
            f"Massive="
            f"{massive_shares_per_contract:g}, "
            f"Saxo="
            f"{saxo_contract_size:g}."
        )


def bridge_massive_quote_to_saxo(
    saxo_client: SaxoClient,
    underlying: str,
    massive_quote: dict[str, Any],
) -> BridgedOptionQuote:

    expiration = str(
        _required_value(
            massive_quote,
            "expiration",
        )
    )[:10]

    strike = float(
        _required_value(
            massive_quote,
            "strike",
        )
    )

    right = _normalize_right(
        _required_value(
            massive_quote,
            "right",
        )
    )

    massive_multiplier = (
        _optional_float(
            massive_quote.get(
                "shares_per_contract"
            )
        )
    )

    contract, saxo_quote = (
        saxo_client
        .get_option_contract_and_quote(
            underlying=underlying,
            expiration=expiration,
            strike=strike,
            put_call=right,
        )
    )

    _validate_contract_identity(
        massive_shares_per_contract=
            massive_multiplier,
        saxo_contract_size=
            contract.contract_size,
    )

    return BridgedOptionQuote(
        underlying=underlying.upper(),
        expiration=expiration,
        strike=strike,
        right=right,
        massive_symbol=(
            massive_quote.get(
                "provider_symbol"
            )
            or massive_quote.get(
                "provider_contract_id"
            )
            or massive_quote.get(
                "option_symbol"
            )
        ),
        massive_bid=_optional_float(
            massive_quote.get("bid")
        ),
        massive_ask=_optional_float(
            massive_quote.get("ask")
        ),
        massive_iv=_optional_float(
            massive_quote.get(
                "implied_volatility"
            )
        ),
        massive_delta=_optional_float(
            massive_quote.get("delta")
        ),
        massive_open_interest=
            _optional_float(
                massive_quote.get(
                    "open_interest"
                )
            ),
        massive_shares_per_contract=
            massive_multiplier,
        saxo_contract=contract,
        saxo_quote=saxo_quote,
    )