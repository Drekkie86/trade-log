"""A small Saxo token-keeper entrypoint, separate from the trading daemon.

Intended for an opt-in systemd timer. It keeps LIVE OAuth credentials
rotating even when nobody opens the Streamlit System page. It never
requests quotes, reads account balances, or submits orders. No secrets
or account identifiers leave this module.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Callable

from src.providers.saxo_auth import (
    SaxoAuthenticationError, SaxoTokenNetworkError,
    _token_is_usable, get_saxo_live_access_token, get_saxo_live_setting,
)


@dataclass(frozen=True)
class SaxoSessionMaintenance:
    state: str
    detail: str
    observed_at: str
    order_authority: bool = False

    def as_dict(self) -> dict:
        return asdict(self)


def keep_saxo_session(
    *,
    setting: Callable[[str], str | None] = get_saxo_live_setting,
    access_provider: Callable[..., str] = get_saxo_live_access_token,
) -> SaxoSessionMaintenance:
    def result(state: str, detail: str) -> SaxoSessionMaintenance:
        return SaxoSessionMaintenance(
            state, detail,
            datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        )

    try:
        if not setting("SAXO_LIVE_APP_KEY"):
            return result("NOT_CONFIGURED", "Saxo LIVE credentials not provisioned.")
        if not setting("SAXO_LIVE_REFRESH_TOKEN") or not setting(
            "SAXO_LIVE_CODE_VERIFIER"
        ):
            return result("LOGIN_REQUIRED", "Interactive Saxo OAuth login required.")

        prior_expiry = setting("SAXO_LIVE_ACCESS_EXPIRES_AT")
        fresh = _token_is_usable(prior_expiry)
        # Provider returns a bearer token: discard it immediately.
        if not access_provider():
            return result("LOGIN_REQUIRED", "Saxo OAuth returned no access token.")
        return result(
            "ACTIVE" if fresh else "REFRESHED",
            "Saxo LIVE OAuth session maintained; no brokerage request performed.",
        )
    except SaxoTokenNetworkError:
        return result("UNREACHABLE", "Saxo OAuth token endpoint unavailable.")
    except (SaxoAuthenticationError, RuntimeError, ValueError, OSError):
        return result("LOGIN_REQUIRED", "Saxo session cannot be renewed; login required.")


def main() -> int:
    health = keep_saxo_session()
    print(json.dumps(health.as_dict(), sort_keys=True))
    # A keeper activated without valid credentials must not appear green.
    return 0 if health.state in {"ACTIVE", "REFRESHED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
