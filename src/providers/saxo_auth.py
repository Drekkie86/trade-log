from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import (
    datetime,
    timedelta,
    timezone,
)

from src.config import (
    get_optional_setting,
    get_required_setting,
    set_local_settings,
)


SAXO_LIVE_TOKEN_URL = (
    "https://live.logonvalidation.net/token"
)

REFRESH_SAFETY_MARGIN_SECONDS = 60


class SaxoAuthenticationError(
    RuntimeError
):
    pass


def _utc_now() -> datetime:
    return datetime.now(
        timezone.utc
    )


def _parse_utc(
    value: str | None,
) -> datetime | None:

    if not value:
        return None

    return datetime.fromisoformat(
        value.replace(
            "Z",
            "+00:00",
        )
    )


def _iso_utc(
    value: datetime,
) -> str:

    return (
        value.replace(microsecond=0)
        .isoformat()
        .replace(
            "+00:00",
            "Z",
        )
    )


def _token_is_usable(
    expires_at: str | None,
) -> bool:

    expiry = _parse_utc(
        expires_at
    )

    if expiry is None:
        return False

    safety_limit = (
        _utc_now()
        + timedelta(
            seconds=
                REFRESH_SAFETY_MARGIN_SECONDS
        )
    )

    return expiry > safety_limit


def refresh_saxo_live_token() -> str:
    app_key = get_required_setting(
        "SAXO_LIVE_APP_KEY"
    )

    refresh_token = (
        get_required_setting(
            "SAXO_LIVE_REFRESH_TOKEN"
        )
    )

    code_verifier = (
        get_required_setting(
            "SAXO_LIVE_CODE_VERIFIER"
        )
    )

    refresh_expires_at = (
        get_optional_setting(
            "SAXO_LIVE_REFRESH_EXPIRES_AT"
        )
    )

    if not _token_is_usable(
        refresh_expires_at
    ):
        raise SaxoAuthenticationError(
            "The Saxo refresh token has expired. "
            "Run: python saxo_live_auth.py"
        )

    body = urllib.parse.urlencode(
        {
            "grant_type":
                "refresh_token",

            "refresh_token":
                refresh_token,

            "client_id":
                app_key,

            "code_verifier":
                code_verifier,
        }
    ).encode("utf-8")

    request = urllib.request.Request(
        SAXO_LIVE_TOKEN_URL,
        data=body,
        method="POST",
        headers={
            "Content-Type":
                "application/"
                "x-www-form-urlencoded",

            "Accept":
                "application/json",
        },
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=30,
        ) as response:

            payload = json.loads(
                response.read().decode(
                    "utf-8"
                )
            )

    except urllib.error.HTTPError as exc:
        body_text = (
            exc.read()
            .decode(
                "utf-8",
                errors="replace",
            )
        )

        safe_body = " ".join(body_text.split())[:500]

        raise SaxoAuthenticationError(
            f"Saxo token refresh failed "
            f"with HTTP {exc.code}: "
            f"{safe_body}"
        ) from exc

    access_token = payload.get(
        "access_token"
    )

    new_refresh_token = payload.get(
        "refresh_token"
    )

    if not access_token:
        raise SaxoAuthenticationError(
            "Saxo refresh response did not "
            "contain an access token."
        )

    if not new_refresh_token:
        raise SaxoAuthenticationError(
            "Saxo refresh response did not "
            "contain a new refresh token."
        )

    expires_in = int(
        payload.get("expires_in")
        or 0
    )

    refresh_expires_in = int(
        payload.get(
            "refresh_token_expires_in"
        )
        or 0
    )

    now = _utc_now()

    set_local_settings(
        {
            "SAXO_LIVE_ACCESS_TOKEN":
                access_token,

            "SAXO_LIVE_ACCESS_EXPIRES_AT":
                _iso_utc(
                    now
                    + timedelta(
                        seconds=expires_in
                    )
                ),

            "SAXO_LIVE_REFRESH_TOKEN":
                new_refresh_token,

            "SAXO_LIVE_REFRESH_EXPIRES_AT":
                _iso_utc(
                    now
                    + timedelta(
                        seconds=
                            refresh_expires_in
                    )
                ),
        }
    )

    return access_token


def get_saxo_live_access_token(*, force_refresh: bool = False) -> str:
    access_token = (
        get_optional_setting(
            "SAXO_LIVE_ACCESS_TOKEN"
        )
    )

    access_expires_at = (
        get_optional_setting(
            "SAXO_LIVE_ACCESS_EXPIRES_AT"
        )
    )

    if (
        not force_refresh
        and access_token
        and _token_is_usable(
            access_expires_at
        )
    ):
        return access_token

    return refresh_saxo_live_token()
