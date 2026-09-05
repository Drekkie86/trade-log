from __future__ import annotations

import base64
import binascii
import ipaddress
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlparse

from src.config import get_runtime_setting


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
COOKIE_KEY_BYTES = {16, 24, 32}


@dataclass(frozen=True)
class SecureEdgeCheck:
    name: str
    state: str
    detail: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class SecureEdgeStatus:
    ready: bool
    public_host: str | None
    redirect_url: str | None
    oidc_issuer_url: str | None
    authorized_email_count: int
    checks: tuple[SecureEdgeCheck, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "ready": self.ready,
            "public_host": self.public_host,
            "redirect_url": self.redirect_url,
            "oidc_issuer_url": self.oidc_issuer_url,
            "authorized_email_count": self.authorized_email_count,
            "checks": [check.as_dict() for check in self.checks],
        }


def _pass(name: str, detail: str) -> SecureEdgeCheck:
    return SecureEdgeCheck(name, "PASS", detail)


def _fail(name: str, detail: str) -> SecureEdgeCheck:
    return SecureEdgeCheck(name, "FAIL", detail)


def _valid_public_host(value: str | None) -> tuple[bool, str]:
    if not value:
        return False, "CHRISTIANIA_PUBLIC_HOST is missing."
    host = value.strip().lower()
    if "://" in host or "/" in host or "@" in host:
        return False, "Public host must be a bare DNS hostname, not a URL."
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".localhost"):
        return False, "Public host must not be localhost."
    try:
        ipaddress.ip_address(host.strip("[]"))
        return False, "Public host must be a DNS hostname, not a raw IP address."
    except ValueError:
        pass
    labels = host.rstrip(".").split(".")
    if len(labels) < 2 or any(
        not label
        or len(label) > 63
        or label[0] == "-"
        or label[-1] == "-"
        or not re.fullmatch(r"[a-z0-9-]+", label)
        for label in labels
    ):
        return False, "Public host is not a valid DNS hostname."
    return True, host.rstrip(".")


def _valid_https_url(value: str | None, *, label: str) -> tuple[bool, str]:
    if not value:
        return False, f"{label} is missing."
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.hostname:
        return False, f"{label} must be an absolute HTTPS URL."
    if parsed.username or parsed.password or parsed.fragment:
        return False, f"{label} must not contain user-info or a fragment."
    return True, value.rstrip("/")


def _decode_cookie_secret(value: str | None) -> tuple[bool, int | None]:
    if not value:
        return False, None
    raw = value.strip().encode("ascii", errors="ignore")
    padding = b"=" * ((4 - len(raw) % 4) % 4)
    try:
        decoded = base64.urlsafe_b64decode(raw + padding)
    except (ValueError, binascii.Error):
        return False, None
    return len(decoded) in COOKIE_KEY_BYTES, len(decoded)


def _authorized_emails(path_value: str | None) -> tuple[Path | None, tuple[str, ...], str | None]:
    if not path_value:
        return None, (), "OAUTH2_PROXY_AUTHENTICATED_EMAILS_FILE is missing."
    path = Path(path_value).expanduser()
    if not path.is_absolute():
        return path, (), "Authorized-emails path must be absolute."
    if not path.is_file():
        return path, (), f"Authorized-emails file does not exist: {path}"
    emails: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        value = raw.strip()
        if not value or value.startswith("#"):
            continue
        if value == "*" or not EMAIL_RE.fullmatch(value):
            return path, (), f"Invalid authorized-email entry: {value!r}"
        emails.append(value.lower())
    unique = tuple(dict.fromkeys(emails))
    if not unique:
        return path, (), "Authorized-emails file contains no user email addresses."
    return path, unique, None



def render_caddyfile(template: str, public_host: str) -> str:
    token = "{{CHRISTIANIA_PUBLIC_HOST}}"
    if template.count(token) != 1:
        raise ValueError("Caddy template must contain exactly one public-host token.")
    ok, normalized = _valid_public_host(public_host)
    if not ok:
        raise ValueError(normalized)
    return template.replace(token, normalized)


def inspect_secure_edge_configuration() -> SecureEdgeStatus:
    checks: list[SecureEdgeCheck] = []

    host_ok, host_detail = _valid_public_host(
        get_runtime_setting("CHRISTIANIA_PUBLIC_HOST")
    )
    host = host_detail if host_ok else None
    checks.append(
        _pass("public-host", f"Public host: {host}")
        if host_ok
        else _fail("public-host", host_detail)
    )

    redirect_value = get_runtime_setting("OAUTH2_PROXY_REDIRECT_URL")
    redirect_ok, redirect_detail = _valid_https_url(
        redirect_value,
        label="OAUTH2_PROXY_REDIRECT_URL",
    )
    redirect = redirect_detail if redirect_ok else None
    if redirect_ok and host:
        expected = f"https://{host}/oauth2/callback"
        if redirect != expected:
            redirect_ok = False
            redirect_detail = f"Redirect URL must exactly equal {expected}."
            redirect = None
    checks.append(
        _pass("oidc-redirect", f"Redirect URL: {redirect}")
        if redirect_ok
        else _fail("oidc-redirect", redirect_detail)
    )

    issuer_ok, issuer_detail = _valid_https_url(
        get_runtime_setting("OAUTH2_PROXY_OIDC_ISSUER_URL"),
        label="OAUTH2_PROXY_OIDC_ISSUER_URL",
    )
    issuer = issuer_detail if issuer_ok else None
    checks.append(
        _pass("oidc-issuer", f"OIDC issuer: {issuer}")
        if issuer_ok
        else _fail("oidc-issuer", issuer_detail)
    )

    client_id = get_runtime_setting("OAUTH2_PROXY_CLIENT_ID")
    checks.append(
        _pass("oidc-client-id", "OIDC client ID is configured.")
        if client_id
        else _fail("oidc-client-id", "OAUTH2_PROXY_CLIENT_ID is missing.")
    )

    client_secret = get_runtime_setting("OAUTH2_PROXY_CLIENT_SECRET")
    checks.append(
        _pass("oidc-client-secret", "OIDC client secret is configured.")
        if client_secret
        else _fail("oidc-client-secret", "OAUTH2_PROXY_CLIENT_SECRET is missing.")
    )

    cookie_ok, cookie_bytes = _decode_cookie_secret(
        get_runtime_setting("OAUTH2_PROXY_COOKIE_SECRET")
    )
    checks.append(
        _pass(
            "session-cookie-secret",
            f"Cookie secret decodes to an accepted {cookie_bytes}-byte key.",
        )
        if cookie_ok
        else _fail(
            "session-cookie-secret",
            "OAUTH2_PROXY_COOKIE_SECRET must be URL-safe base64 encoding of a 16, 24, or 32 byte key.",
        )
    )

    path, emails, email_error = _authorized_emails(
        get_runtime_setting("OAUTH2_PROXY_AUTHENTICATED_EMAILS_FILE")
    )
    checks.append(
        _pass(
            "authorized-emails",
            f"{len(emails)} explicit authorized email(s) loaded from {path}.",
        )
        if email_error is None
        else _fail("authorized-emails", email_error)
    )

    ready = all(check.state == "PASS" for check in checks)
    return SecureEdgeStatus(
        ready=ready,
        public_host=host,
        redirect_url=redirect,
        oidc_issuer_url=issuer,
        authorized_email_count=len(emails),
        checks=tuple(checks),
    )
