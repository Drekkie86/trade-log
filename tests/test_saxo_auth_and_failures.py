import io
import json
import urllib.error

import pytest

from src.providers.saxo import (
    SaxoApiAuthenticationError,
    SaxoClient,
    SaxoRootResolutionError,
)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def http_error(code, body="error"):
    return urllib.error.HTTPError(
        "https://example.test",
        code,
        "error",
        hdrs=None,
        fp=io.BytesIO(body.encode("utf-8")),
    )


def test_client_refreshes_once_after_401(monkeypatch):
    calls = []
    tokens = []

    def token_provider(*, force_refresh=False):
        tokens.append(force_refresh)
        return "new" if force_refresh else "old"

    def fake_urlopen(request, timeout):
        calls.append(request.headers.get("Authorization"))
        if len(calls) == 1:
            raise http_error(401)
        return FakeResponse({"Data": []})

    monkeypatch.setattr(
        "urllib.request.urlopen",
        fake_urlopen,
    )

    client = SaxoClient(token_provider=token_provider)
    result = client._get_json("/test")

    assert result == {"Data": []}
    assert tokens == [False, True, False]
    assert client.consume_retry_count() == 1


def test_second_401_is_authentication_failure(monkeypatch):
    def token_provider(*, force_refresh=False):
        return "token"

    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request, timeout: (_ for _ in ()).throw(http_error(401)),
    )

    client = SaxoClient(token_provider=token_provider)

    with pytest.raises(SaxoApiAuthenticationError):
        client._get_json("/test")


def test_root_resolution_uses_typed_error(monkeypatch):
    client = SaxoClient(access_token="token")
    monkeypatch.setattr(
        client,
        "search_option_roots",
        lambda keywords: [],
    )

    with pytest.raises(SaxoRootResolutionError):
        client.find_option_root("AAPL")
