"""Saxo health: read-only, redacted, with separate auth and quote statuses."""
from src.providers.saxo import (
    SAXO_LIVE_BASE_URL, SaxoApiAuthenticationError,
    SaxoNetworkError, SaxoRateLimitError,
)
from src.providers.saxo_live_health_v1 import probe_saxo_live
from src.ui.home_pages import system_checks, system_verdict


def config(*, app="application", refresh="refresh", verifier="pkce",
           expires="2026-10-26T00:00:00Z"):
    values = {
        "SAXO_LIVE_APP_KEY": app,
        "SAXO_LIVE_REFRESH_TOKEN": refresh,
        "SAXO_LIVE_CODE_VERIFIER": verifier,
        "SAXO_LIVE_REFRESH_EXPIRES_AT": expires,
    }
    return values.get


class Client:
    requested = []
    response = {
        "Active": True,
        "MarketDataViaOpenApiTermsAccepted": True,
        "LegalAssetTypes": ["Stock", "StockOption"],
        "Name": "sensitive-real-person",
        "UserKey": "sensitive-key",
    }
    error = None

    def __init__(self, *, token_provider, base_url, timeout_seconds):
        assert base_url == SAXO_LIVE_BASE_URL
        assert timeout_seconds <= 8
        self.provider = token_provider

    def _get_json(self, path):
        Client.requested.append(path)
        if Client.error:
            raise Client.error
        return dict(Client.response)


def probe(setting):
    return probe_saxo_live(
        setting=setting, token_provider=lambda **k: "NO_SECRET",
        client_factory=Client,
    )


def setup_function():
    Client.requested.clear()
    Client.error = None
    Client.response = {
        "Active": True,
        "MarketDataViaOpenApiTermsAccepted": True,
        "LegalAssetTypes": ["Stock", "StockOption"],
        "Name": "sensitive-real-person",
        "UserKey": "sensitive-key",
    }


def test_unconfigured_connection_is_nonblocking_and_never_uses_api():
    status = probe(config(app=None, refresh=None))
    assert status.state == "NOT_CONFIGURED"
    assert status.auth_ok is None
    assert Client.requested == []
    assert "sensitive" not in str(status.as_dict())


def test_initial_oauth_login_needed_before_api_probe():
    status = probe(config(refresh=None))
    assert status.state == "LOGIN_REQUIRED"
    assert status.auth_ok is False
    assert Client.requested == []


def test_live_api_reads_only_user_identity_without_reporting_identity():
    status = probe(config())
    assert status.state == "CONNECTED_READ_ONLY"
    assert status.auth_ok
    assert status.stock_option_eligible
    assert status.market_data_terms_accepted
    assert status.quote_state == "UNVERIFIED_STOCK_AND_OPRA_QUOTES"
    assert status.environment == "LIVE"
    assert status.order_authority is False
    assert Client.requested == ["/port/v1/users/me"]
    assert "sensitive" not in str(status.as_dict())


def test_successful_login_is_not_equivalent_to_market_data_terms_or_options():
    Client.response["MarketDataViaOpenApiTermsAccepted"] = False
    status = probe(config())
    assert status.state == "MARKET_DATA_TERMS_REQUIRED"
    assert status.auth_ok is True
    assert status.quote_state == "TERMS_NOT_ACCEPTED"
    Client.response["MarketDataViaOpenApiTermsAccepted"] = True
    Client.response["LegalAssetTypes"] = ["Stock"]
    status = probe(config())
    assert status.state == "STOCK_OPTIONS_NOT_ENABLED"
    assert status.auth_ok is True


def test_inactive_user_and_invalid_response_fail_closed():
    Client.response["Active"] = False
    assert probe(config()).state == "ACCOUNT_INACTIVE"
    Client.response = {"UserKey": "sensitive"}
    assert probe(config()).state == "UNVERIFIED_RESPONSE"


def test_expired_refresh_is_auth_issue_not_provider_market_data_issue():
    from src.providers.saxo_auth import SaxoAuthenticationError
    def expired(**kwargs):
        raise SaxoAuthenticationError("refresh token secret=SENSITIVE")
    status = probe_saxo_live(
        setting=config(), token_provider=expired,
        client_factory=lambda **kwargs: type("C", (), {
            "_get_json": lambda self, path: expired(),
        })(),
    )
    assert status.state == "LOGIN_REQUIRED"
    assert "SENSITIVE" not in status.detail


def test_network_rate_limit_and_rejected_permission_have_distinct_statuses():
    for error, expected in (
        (SaxoRateLimitError("secret abc"), "RATE_LIMITED"),
        (SaxoNetworkError("secret abc"), "UNREACHABLE"),
        (SaxoApiAuthenticationError("secret abc", status_code=401), "LOGIN_REQUIRED"),
        (SaxoApiAuthenticationError("secret abc", status_code=403), "API_PERMISSION_DENIED"),
    ):
        Client.error = error
        health = probe(config())
        assert health.state == expected
        assert "abc" not in health.detail


def test_saxo_is_two_explicit_checks_without_blocking_core_when_unconfigured():
    snapshot = {"daemon_health": {"state": "HEALTHY"},
                "database": {"schema_version": 38, "expected_schema_version": 38,
                             "quick_check": "ok"},
                "latest_iteration": {"status": "COMPLETED", "scheduled_for": "2026-10-24T12:00:00Z"}}
    theta = {"ready": True}
    backup = {"total_files": 1, "latest_valid_age_hours": 2}
    health = probe(config())
    rows = system_checks(snapshot, theta, backup, saxo=health.as_dict())
    statuses = {label: state for label, state, _ in rows}
    assert statuses["Saxo LIVE"] is True
    assert statuses["Saxo market data"] is None
    assert system_verdict(rows)[0] == "warn"
    rows = system_checks(snapshot, theta, backup,
                         saxo=probe(config(app=None)).as_dict())
    statuses = {label: state for label, state, _ in rows}
    assert statuses["Saxo LIVE"] is None
    assert statuses["Saxo market data"] is None


def test_market_data_terms_fail_health_independently():
    Client.response["MarketDataViaOpenApiTermsAccepted"] = False
    rows = system_checks({}, {"state": "NOT_PROBED"}, {"total_files": 0},
                         saxo=probe(config()).as_dict())
    assert {label: ok for label, ok, _ in rows}["Saxo market data"] is False
