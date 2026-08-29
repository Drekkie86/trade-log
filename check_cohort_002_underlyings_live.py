from __future__ import annotations

from src.config import get_required_setting
from src.providers.bridge import (
    OptionBridgeError,
    bridge_massive_quote_to_saxo,
)
from src.providers.massive import (
    MassiveClient,
    normalize_massive_option_chain,
)
from src.providers.saxo import (
    SaxoClient,
    SaxoError,
)
from src.providers.saxo_auth import (
    get_saxo_live_access_token,
)


UNDERLYINGS = (
    "AAPL",
    "XOM",
    "JPM",
)

MIN_DTE = 7
MAX_DTE = 45
MAX_BRIDGE_ATTEMPTS = 5


def sort_key(quote):
    value = quote.get("open_interest")
    if value is None:
        return -1.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return -1.0


def main() -> int:
    massive = MassiveClient(
        api_key=get_required_setting(
            "MASSIVE_API_KEY"
        )
    )

    saxo = SaxoClient(
        access_token=(
            get_saxo_live_access_token()
        )
    )

    failures: list[str] = []

    print()
    print(
        "Christiania - Cohort 002 "
        "underlying seam check"
    )
    print(
        "============================================"
    )
    print(
        "Read-only. No orders. No database writes."
    )
    print()

    for symbol in UNDERLYINGS:
        print(symbol)
        print("-" * len(symbol))

        try:
            payload = massive.get_option_chain(
                symbol,
                min_dte=MIN_DTE,
                max_dte=MAX_DTE,
                page_limit=250,
                max_pages=20,
                require_complete=True,
            )

            _, quotes = (
                normalize_massive_option_chain(
                    symbol,
                    payload,
                )
            )

            print(
                f"Massive normalized contracts: "
                f"{len(quotes)}"
            )
            print(
                f"Massive pages fetched:        "
                f"{payload.get('pages_fetched')}"
            )
            print(
                f"Massive truncated:            "
                f"{payload.get('truncated')}"
            )

        except Exception as exc:
            failures.append(
                f"{symbol}: Massive failure: {exc}"
            )
            print(f"FAIL Massive: {exc}")
            print()
            continue

        try:
            underlying_quote = (
                saxo.get_underlying_quote_for_symbol(
                    symbol
                )
            )

            print(
                f"Saxo underlying UIC:          "
                f"{underlying_quote.uic}"
            )
            print(
                f"Saxo market state:            "
                f"{underlying_quote.market_state}"
            )
            print(
                f"Saxo quote quality:           "
                f"{underlying_quote.quality.value}"
            )
            print(
                f"Saxo executable:              "
                f"{underlying_quote.is_executable}"
            )
            print(
                f"Saxo delay minutes:           "
                f"{underlying_quote.delayed_by_minutes}"
            )

        except SaxoError as exc:
            failures.append(
                f"{symbol}: Saxo underlying failure: "
                f"{exc}"
            )
            print(f"FAIL Saxo underlying: {exc}")
            print()
            continue

        ordered = sorted(
            quotes,
            key=sort_key,
            reverse=True,
        )

        attempts = 0
        bridge_ok = False

        for quote in ordered:
            if attempts >= MAX_BRIDGE_ATTEMPTS:
                break

            oi = quote.get("open_interest")
            if oi in (None, 0):
                continue

            attempts += 1

            try:
                result = (
                    bridge_massive_quote_to_saxo(
                        saxo_client=saxo,
                        underlying=symbol,
                        massive_quote=quote,
                    )
                )

            except (
                SaxoError,
                OptionBridgeError,
                ValueError,
            ) as exc:
                print(
                    f"Bridge attempt {attempts}: FAIL "
                    f"({exc})"
                )
                continue

            bridge_ok = True

            print(
                f"Bridge option UIC:            "
                f"{result.saxo_contract.uic}"
            )
            print(
                f"Bridge option quality:        "
                f"{result.saxo_quote.quality.value}"
            )
            print(
                f"Bridge option executable:     "
                f"{result.saxo_quote.is_executable}"
            )
            print(
                f"Bridge option delay minutes:  "
                f"{result.saxo_quote.delayed_by_minutes}"
            )
            break

        if not bridge_ok:
            failures.append(
                f"{symbol}: no Massive->Saxo option "
                f"bridge after {attempts} attempts"
            )
            print(
                "FAIL: no Massive->Saxo option bridge"
            )
        else:
            print("SEAM RESULT: PASS")

        print()

    print(
        "============================================"
    )

    if failures:
        print("OVERALL RESULT: FAIL")
        print()
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("OVERALL RESULT: PASS")
    print(
        "Provider identity/resolution seams are "
        "available for AAPL, XOM and JPM."
    )
    print(
        "Quote quality is reported separately and "
        "is not required to be EXECUTABLE for this "
        "identity seam check."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
