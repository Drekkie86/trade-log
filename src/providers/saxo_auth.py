"""Saxo OAuth PKCE refresh with atomic rotating-credential persistence.

Saxo invalidates a refresh token after rotation. A process-wide *and*
cross-process lock must guard reading the old token, exchanging it, and
persisting BOTH new tokens as a single atomic file replacement.

Production uses CHRISTIANIA_SAXO_TOKEN_STORE outside the application release.
The legacy local .env path remains available on the user's trusted PC.
No raw credential, OAuth response body or user identifier is logged.
"""
from __future__ import annotations

import json
import os
import stat
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

from src.config import (
    ENV_FILE, _local_env_fallback_disabled, _settings_file_lock,
    _set_local_settings_unlocked, get_optional_setting, read_env_file,
)

SAXO_LIVE_TOKEN_URL = "https://live.logonvalidation.net/token"
REFRESH_SAFETY_MARGIN_SECONDS = 60


class SaxoAuthenticationError(RuntimeError):
    pass


class SaxoTokenNetworkError(SaxoAuthenticationError):
    pass


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _parse_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return None
        return parsed.astimezone(UTC)
    except ValueError:
        return None


def _iso_utc(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _token_is_usable(expires_at: str | None) -> bool:
    expiry = _parse_utc(expires_at)
    return bool(expiry and expiry > _utc_now() + timedelta(
        seconds=REFRESH_SAFETY_MARGIN_SECONDS
    ))


def _store_path() -> Path:
    separate = os.environ.get("CHRISTIANIA_SAXO_TOKEN_STORE")
    if not separate:
        if _local_env_fallback_disabled():
            raise SaxoAuthenticationError(
                "A dedicated Saxo token store is required in the server runtime."
            )
        return ENV_FILE

    path = Path(separate).expanduser()
    if not path.is_absolute():
        raise SaxoAuthenticationError("Saxo token store path must be absolute.")
    if not path.parent.is_dir() or path.parent.is_symlink() or path.is_symlink():
        raise SaxoAuthenticationError("Unsafe Saxo token store path.")
    if path.exists() and os.name != "nt":
        if stat.S_IMODE(path.stat().st_mode) & 0o077:
            raise SaxoAuthenticationError(
                "Saxo token store must have owner-only file permissions."
            )
    return path


def _setting(path: Path, name: str) -> str | None:
    if path == ENV_FILE:
        return get_optional_setting(name)
    return read_env_file(path).get(name)


def _refresh_under_lock(
    *,
    store: Path,
    force_refresh: bool,
    prior_access_token: str | None,
) -> str:
    app_key = _setting(store, "SAXO_LIVE_APP_KEY")
    access = _setting(store, "SAXO_LIVE_ACCESS_TOKEN")
    access_expires = _setting(store, "SAXO_LIVE_ACCESS_EXPIRES_AT")

    # Another process already successfully refreshed the token while
    # this caller waited for the lock: reuse it instead of invalidating it.
    if access and _token_is_usable(access_expires):
        if not force_refresh or (
            prior_access_token is not None and prior_access_token != access
        ):
            return access

    refresh = _setting(store, "SAXO_LIVE_REFRESH_TOKEN")
    verifier = _setting(store, "SAXO_LIVE_CODE_VERIFIER")
    refresh_expires = _setting(store, "SAXO_LIVE_REFRESH_EXPIRES_AT")
    if not app_key or not refresh or not verifier or not _token_is_usable(
        refresh_expires
    ):
        raise SaxoAuthenticationError(
            "Saxo refresh credentials are missing or expired. "
            "Interactive OAuth login is required."
        )

    body = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "refresh_token": refresh,
        "client_id": app_key,
        "code_verifier": verifier,
    }).encode("utf-8")
    request = urllib.request.Request(
        SAXO_LIVE_TOKEN_URL,
        data=body, method="POST",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # The provider body may echo secrets, tokens or account identifiers.
        # Never include it in an exception that appears on the dashboard.
        raise SaxoAuthenticationError(
            f"Saxo OAuth refresh rejected (HTTP {exc.code})."
        ) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise SaxoTokenNetworkError("Saxo OAuth token endpoint unreachable.") from None
    except (ValueError, UnicodeError):
        raise SaxoAuthenticationError("Saxo OAuth response could not be decoded.") from None
    if not isinstance(payload, dict):
        raise SaxoAuthenticationError("Saxo OAuth returned an invalid response.")

    new_access = payload.get("access_token")
    new_refresh = payload.get("refresh_token")
    try:
        lifetime = int(payload.get("expires_in", 0))
        refresh_lifetime = int(payload.get("refresh_token_expires_in", 0))
    except (ValueError, TypeError):
        raise SaxoAuthenticationError("Saxo OAuth returned invalid token lifetimes.")
    if (
        not isinstance(new_access, str) or not new_access
        or not isinstance(new_refresh, str) or not new_refresh
        or lifetime <= REFRESH_SAFETY_MARGIN_SECONDS
        or refresh_lifetime <= REFRESH_SAFETY_MARGIN_SECONDS
    ):
        raise SaxoAuthenticationError(
            "Saxo OAuth did not supply complete rotating credentials."
        )

    now = _utc_now()
    _set_local_settings_unlocked({
        "SAXO_LIVE_ACCESS_TOKEN": new_access,
        "SAXO_LIVE_ACCESS_EXPIRES_AT": _iso_utc(now + timedelta(seconds=lifetime)),
        "SAXO_LIVE_REFRESH_TOKEN": new_refresh,
        "SAXO_LIVE_REFRESH_EXPIRES_AT": _iso_utc(
            now + timedelta(seconds=refresh_lifetime)
        ),
    }, path=store)
    return new_access


def refresh_saxo_live_token(
    *,
    force_refresh: bool = True,
    prior_access_token: str | None = None,
) -> str:
    store = _store_path()
    # The lock covers the actual HTTP refresh exchange AND atomic file
    # rotation. Concurrency across daemon and UI cannot replay old tokens.
    with _settings_file_lock(store):
        return _refresh_under_lock(
            store=store, force_refresh=force_refresh,
            prior_access_token=prior_access_token,
        )


def get_saxo_live_setting(name: str) -> str | None:
    """Read an optional setting for health, without attempting an OAuth call."""
    configured = os.environ.get("CHRISTIANIA_SAXO_TOKEN_STORE")
    if configured and not Path(configured).is_file():
        return None
    if _local_env_fallback_disabled() and not configured:
        return None
    return _setting(_store_path(), name)


def get_saxo_live_access_token(*, force_refresh: bool = False) -> str:
    store = _store_path()
    access = _setting(store, "SAXO_LIVE_ACCESS_TOKEN")
    if not force_refresh and access and _token_is_usable(
        _setting(store, "SAXO_LIVE_ACCESS_EXPIRES_AT")
    ):
        return access
    return refresh_saxo_live_token(
        force_refresh=force_refresh,
        prior_access_token=access,
    )
