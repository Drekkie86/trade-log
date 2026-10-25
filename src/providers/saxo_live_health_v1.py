"""Read-only Saxo LIVE connectivity and entitlement health.

The only broker request is GET /port/v1/users/me. This verifies OAuth
session and *account-level eligibility*, not usable US stock/OPRA quotes.
Never return user keys, raw provider payloads, bearer/refresh tokens or
broker error bodies. This module cannot place orders.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Callable

from src.providers.saxo import (
    SAXO_LIVE_BASE_URL, SaxoApiAuthenticationError, SaxoClient,
    SaxoNetworkError, SaxoRateLimitError, SaxoError,
)
from src.providers.saxo_auth import (
    SaxoAuthenticationError, SaxoTokenNetworkError,
    get_saxo_live_access_token, get_saxo_live_setting,
)


@dataclass(frozen=True)
class SaxoHealth:
    state: str
    auth_ok: bool | None
    detail: str
    quote_state: str
    market_data_terms_accepted: bool | None
    stock_option_eligible: bool | None
    checked_at: str
    environment: str = "LIVE"
    order_authority: bool = False

    def as_dict(self) -> dict:
        return asdict(self)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def probe_saxo_live(
    *,
    setting: Callable[[str], str | None] = get_saxo_live_setting,
    token_provider: Callable[..., str] = get_saxo_live_access_token,
    client_factory: Callable[..., SaxoClient] = SaxoClient,
) -> SaxoHealth:
    """One cached read-only probe; never refresh or call Saxo without setup.

    Market data is NOT qualified until a separate *timestamped real quote*
    probe confirms exact exchange entitlements and side/depth quality.
    """
    def result(state: str, ok: bool | None, detail: str,
               terms: bool | None = None, options: bool | None = None):
        quote_state = (
            "TERMS_NOT_ACCEPTED" if terms is False
            else "UNVERIFIED_STOCK_AND_OPRA_QUOTES"
        )
        return SaxoHealth(
            state=state, auth_ok=ok, detail=detail,
            quote_state=quote_state,
            market_data_terms_accepted=terms,
            stock_option_eligible=options,
            checked_at=_now(),
        )

    try:
        app_key = setting("SAXO_LIVE_APP_KEY")
        refresh = setting("SAXO_LIVE_REFRESH_TOKEN")
        verifier = setting("SAXO_LIVE_CODE_VERIFIER")
        expiry = setting("SAXO_LIVE_REFRESH_EXPIRES_AT")
        if not app_key:
            return result(
                "NOT_CONFIGURED", None,
                "Saxo LIVE application not configured. No broker request made.",
            )
        if not refresh or not verifier or not expiry:
            return result(
                "LOGIN_REQUIRED", False,
                "Saxo LIVE requires interactive OAuth authorization.",
            )

        # User information is discarded; do not log sensitive fields.
        client = client_factory(
            token_provider=token_provider,
            base_url=SAXO_LIVE_BASE_URL,
            timeout_seconds=8,
        )
        payload = client._get_json("/port/v1/users/me")
        if not isinstance(payload, dict) or not isinstance(payload.get("Active"), bool):
            return result(
                "UNVERIFIED_RESPONSE", False,
                "Saxo did not return a valid active-account status.",
            )
        if payload["Active"] is not True:
            return result(
                "ACCOUNT_INACTIVE", False,
                "Saxo authenticated but the user is not active.",
            )
        terms = payload.get("MarketDataViaOpenApiTermsAccepted")
        if not isinstance(terms, bool):
            terms = None
        asset_types = payload.get("LegalAssetTypes")
        options = (
            "StockOption" in asset_types
            if isinstance(asset_types, list) and all(isinstance(x, str) for x in asset_types)
            else None
        )
        if terms is False:
            return result(
                "MARKET_DATA_TERMS_REQUIRED", True,
                "Connected to Saxo LIVE, but OpenAPI market-data terms are not accepted.",
                terms, options,
            )
        if options is False:
            return result(
                "STOCK_OPTIONS_NOT_ENABLED", True,
                "Connected to Saxo LIVE, but stock options are not an eligible asset type.",
                terms, options,
            )
        return result(
            "CONNECTED_READ_ONLY", True,
            "Saxo LIVE user endpoint answered. Live US stocks and OPRA quote "
            "entitlements are not yet verified.",
            terms, options,
        )
    except SaxoRateLimitError:
        return result("RATE_LIMITED", False, "Saxo OpenAPI rate limit reached.")
    except SaxoNetworkError:
        return result("UNREACHABLE", False, "Saxo OpenAPI could not be reached.")
    except SaxoApiAuthenticationError as exc:
        if exc.status_code == 403:
            return result(
                "API_PERMISSION_DENIED", False,
                "Saxo rejected the read-only API request; check application permissions.",
            )
        return result(
            "LOGIN_REQUIRED", False,
            "Saxo session was rejected. Interactive login is required.",
        )
    except SaxoTokenNetworkError:
        return result(
            "UNREACHABLE", False, "Saxo OAuth token endpoint unreachable.",
        )
    except (SaxoAuthenticationError, RuntimeError):
        return result(
            "LOGIN_REQUIRED", False,
            "Saxo session cannot be refreshed. Interactive login is required.",
        )
    except (SaxoError, ValueError, TypeError, KeyError, OSError):
        return result("PROBE_FAILED", False, "Read-only Saxo health probe failed.")
