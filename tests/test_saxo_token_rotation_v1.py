"""Saxo OAuth refresh: rotating tokens, safe persistent store, no disclosure."""
import io
import json
import os
import threading
import urllib.error
import urllib.parse
from datetime import UTC, datetime, timedelta

import pytest

from src.providers.saxo_auth import (
    SaxoAuthenticationError, get_saxo_live_access_token,
    get_saxo_live_setting, refresh_saxo_live_token,
)


def expires(minutes):
    return (datetime.now(UTC) + timedelta(minutes=minutes)).isoformat()


def seed(tmp_path, monkeypatch, *, minutes=-1):
    path = tmp_path / "private-saxo.env"
    path.write_text(
        "SAXO_LIVE_APP_KEY=app-test\n"
        "SAXO_LIVE_CODE_VERIFIER=secret-verifier\n"
        "SAXO_LIVE_REFRESH_TOKEN=refresh-old\n"
        f"SAXO_LIVE_REFRESH_EXPIRES_AT={expires(120)}\n"
        "SAXO_LIVE_ACCESS_TOKEN=access-old\n"
        f"SAXO_LIVE_ACCESS_EXPIRES_AT={expires(minutes)}\n",
        encoding="utf8",
    )
    if os.name != "nt":
        path.chmod(0o600)
    monkeypatch.setenv("CHRISTIANIA_SAXO_TOKEN_STORE", str(path))
    return path


class Response:
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self):
        return json.dumps({
            "access_token": "access-new",
            "refresh_token": "refresh-new",
            "expires_in": 1200,
            "refresh_token_expires_in": 2400,
        }).encode("utf8")


def test_successful_rotation_persists_both_tokens_atomically(tmp_path, monkeypatch):
    path = seed(tmp_path, monkeypatch)
    calls = []
    def post(request, timeout):
        calls.append((request.full_url, request.data))
        return Response()
    monkeypatch.setattr("urllib.request.urlopen", post)
    token = get_saxo_live_access_token()
    assert token == "access-new"
    assert get_saxo_live_setting("SAXO_LIVE_REFRESH_TOKEN") == "refresh-new"
    assert get_saxo_live_access_token() == "access-new"
    assert len(calls) == 1
    assert b"refresh-old" in calls[0][1]
    assert "access-old" not in path.read_text()
    if os.name != "nt":
        assert os.stat(path).st_mode & 0o077 == 0
        assert os.stat(path.with_name(path.name + ".lock")).st_mode & 0o077 == 0


def test_two_concurrent_refreshes_reuse_newly_rotated_token(tmp_path, monkeypatch):
    seed(tmp_path, monkeypatch)
    requests = []
    lock = threading.Lock()
    def post(request, timeout):
        with lock:
            requests.append(request.data)
        return Response()
    monkeypatch.setattr("urllib.request.urlopen", post)
    barrier = threading.Barrier(3)
    results = []
    def job():
        barrier.wait()
        results.append(get_saxo_live_access_token())
    threads = [threading.Thread(target=job) for _ in range(2)]
    for t in threads:
        t.start()
    barrier.wait()
    for t in threads:
        t.join(timeout=5)
    assert sorted(results) == ["access-new", "access-new"]
    assert len(requests) == 1


def test_401_force_refresh_rotates_valid_token_once(tmp_path, monkeypatch):
    seed(tmp_path, monkeypatch, minutes=5)
    calls = []
    def post(request, timeout):
        calls.append(request)
        return Response()
    monkeypatch.setattr("urllib.request.urlopen", post)
    assert get_saxo_live_access_token() == "access-old"
    assert get_saxo_live_access_token(force_refresh=True) == "access-new"
    assert len(calls) == 1
    assert get_saxo_live_access_token() == "access-new"


def test_invalid_refresh_does_not_make_network_call(tmp_path, monkeypatch):
    path = seed(tmp_path, monkeypatch)
    txt = path.read_text()
    path.write_text(txt.replace(f"REFRESH_EXPIRES_AT={expires(120)}",
                                f"REFRESH_EXPIRES_AT={expires(-1)}"))
    # Date precision across test lines is not important; replace the line.
    lines = path.read_text().splitlines()
    lines = [
        f"SAXO_LIVE_REFRESH_EXPIRES_AT={expires(-1)}"
        if line.startswith("SAXO_LIVE_REFRESH_EXPIRES_AT=") else line
        for line in lines
    ]
    path.write_text("\n".join(lines) + "\n")
    monkeypatch.setattr("urllib.request.urlopen",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("expired token made a request")))
    with pytest.raises(SaxoAuthenticationError, match="login is required"):
        get_saxo_live_access_token()


def test_server_requires_persistent_secure_token_store(monkeypatch):
    monkeypatch.delenv("CHRISTIANIA_SAXO_TOKEN_STORE", raising=False)
    monkeypatch.setenv("CHRISTIANIA_DISABLE_LOCAL_ENV_FALLBACK", "1")
    with pytest.raises(SaxoAuthenticationError, match="dedicated"):
        get_saxo_live_access_token()


def test_refresh_does_not_leak_provider_error_body(tmp_path, monkeypatch):
    seed(tmp_path, monkeypatch)
    def error(*a, **k):
        raise urllib.error.HTTPError(
            "https://example.invalid", 400, "failed", None,
            io.BytesIO(b"refresh_token=SUPER_SECRET_TOKEN&account_name=SECRET"),
        )
    monkeypatch.setattr("urllib.request.urlopen", error)
    with pytest.raises(SaxoAuthenticationError) as exc:
        refresh_saxo_live_token()
    assert "SUPER_SECRET" not in str(exc.value)
    assert "SECRET" not in str(exc.value)
    assert "HTTP 400" in str(exc.value)


def test_untrusted_store_path_fails_before_network(tmp_path, monkeypatch):
    monkeypatch.setenv("CHRISTIANIA_SAXO_TOKEN_STORE", "relative.env")
    with pytest.raises(SaxoAuthenticationError, match="absolute"):
        get_saxo_live_access_token()
    path = tmp_path / "missing-parent" / "saxo.env"
    monkeypatch.setenv("CHRISTIANIA_SAXO_TOKEN_STORE", str(path))
    with pytest.raises(SaxoAuthenticationError, match="Unsafe"):
        get_saxo_live_access_token()
