from __future__ import annotations

import base64
from pathlib import Path

from src.operations.secure_edge import inspect_secure_edge_configuration, render_caddyfile


def _valid_env(monkeypatch, tmp_path):
    allow = tmp_path / "authorized.txt"
    allow.write_text("dirk@example.com\n", encoding="utf-8")
    monkeypatch.setenv("CHRISTIANIA_PUBLIC_HOST", "christiania.example.com")
    monkeypatch.setenv("OAUTH2_PROXY_REDIRECT_URL", "https://christiania.example.com/oauth2/callback")
    monkeypatch.setenv("OAUTH2_PROXY_OIDC_ISSUER_URL", "https://login.example.com/tenant/v2.0")
    monkeypatch.setenv("OAUTH2_PROXY_CLIENT_ID", "client-id")
    monkeypatch.setenv("OAUTH2_PROXY_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("OAUTH2_PROXY_COOKIE_SECRET", base64.urlsafe_b64encode(b"x" * 32).decode())
    monkeypatch.setenv("OAUTH2_PROXY_AUTHENTICATED_EMAILS_FILE", str(allow.resolve()))


def test_secure_edge_accepts_strict_oidc_configuration(monkeypatch, tmp_path):
    _valid_env(monkeypatch, tmp_path)
    status = inspect_secure_edge_configuration()
    assert status.ready is True
    assert status.public_host == "christiania.example.com"
    assert status.authorized_email_count == 1


def test_secure_edge_rejects_localhost_and_raw_ip(monkeypatch, tmp_path):
    _valid_env(monkeypatch, tmp_path)
    for host in ("localhost", "127.0.0.1"):
        monkeypatch.setenv("CHRISTIANIA_PUBLIC_HOST", host)
        status = inspect_secure_edge_configuration()
        assert status.ready is False
        assert next(c for c in status.checks if c.name == "public-host").state == "FAIL"


def test_secure_edge_rejects_redirect_not_exactly_bound_to_host(monkeypatch, tmp_path):
    _valid_env(monkeypatch, tmp_path)
    monkeypatch.setenv("OAUTH2_PROXY_REDIRECT_URL", "https://evil.example/oauth2/callback")
    status = inspect_secure_edge_configuration()
    assert status.ready is False
    assert next(c for c in status.checks if c.name == "oidc-redirect").state == "FAIL"


def test_secure_edge_requires_https_oidc_issuer(monkeypatch, tmp_path):
    _valid_env(monkeypatch, tmp_path)
    monkeypatch.setenv("OAUTH2_PROXY_OIDC_ISSUER_URL", "http://login.example.com")
    assert inspect_secure_edge_configuration().ready is False


def test_secure_edge_rejects_weak_cookie_secret(monkeypatch, tmp_path):
    _valid_env(monkeypatch, tmp_path)
    monkeypatch.setenv("OAUTH2_PROXY_COOKIE_SECRET", base64.urlsafe_b64encode(b"short").decode())
    assert inspect_secure_edge_configuration().ready is False


def test_secure_edge_rejects_authorization_wildcard(monkeypatch, tmp_path):
    _valid_env(monkeypatch, tmp_path)
    path = tmp_path / "wildcard.txt"
    path.write_text("*\n", encoding="utf-8")
    monkeypatch.setenv("OAUTH2_PROXY_AUTHENTICATED_EMAILS_FILE", str(path.resolve()))
    status = inspect_secure_edge_configuration()
    assert status.ready is False
    assert status.authorized_email_count == 0


def test_secure_edge_requires_absolute_authorized_email_path(monkeypatch, tmp_path):
    _valid_env(monkeypatch, tmp_path)
    monkeypatch.setenv("OAUTH2_PROXY_AUTHENTICATED_EMAILS_FILE", "relative.txt")
    assert inspect_secure_edge_configuration().ready is False


def test_render_caddyfile_accepts_only_validated_hostname():
    template = "{{CHRISTIANIA_PUBLIC_HOST}} {\n reverse_proxy 127.0.0.1:4180\n}\n"
    rendered = render_caddyfile(template, "christiania.example.com")
    assert rendered.startswith("christiania.example.com")
    import pytest
    with pytest.raises(ValueError):
        render_caddyfile(template, "https://evil.example")
