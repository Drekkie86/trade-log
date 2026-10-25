"""Saxo's rotating refresh token needs independent uptime from Streamlit."""
from pathlib import Path

from src.operations.saxo_session_keeper_v1 import keep_saxo_session
from src.providers.saxo_auth import SaxoAuthenticationError

ROOT = Path(__file__).resolve().parents[1]


def conf(*, app="app", refresh="refresh", verifier="verifier",
         access_expiry="2099-01-01T00:00:00Z"):
    d = {"SAXO_LIVE_APP_KEY": app,
         "SAXO_LIVE_REFRESH_TOKEN": refresh,
         "SAXO_LIVE_CODE_VERIFIER": verifier,
         "SAXO_LIVE_ACCESS_EXPIRES_AT": access_expiry}
    return d.get


def test_session_keeper_does_not_need_market_data_or_order_permissions():
    seen=[]
    status = keep_saxo_session(
        setting=conf(), access_provider=lambda: seen.append("refresh-if-needed") or "bearer",
    )
    assert status.state == "ACTIVE"
    assert status.order_authority is False
    assert seen == ["refresh-if-needed"]
    assert "bearer" not in str(status.as_dict())


def test_session_keeper_refreshes_when_access_is_old():
    status = keep_saxo_session(
        setting=conf(access_expiry="2025-01-01T00:00:00Z"),
        access_provider=lambda: "bearer-secret",
    )
    assert status.state == "REFRESHED"
    assert "bearer-secret" not in status.detail


def test_unconfigured_or_invalid_credentials_fail_without_network():
    never = lambda: (_ for _ in ()).throw(AssertionError("network called"))
    assert keep_saxo_session(setting=conf(app=None),
                             access_provider=never).state == "NOT_CONFIGURED"
    assert keep_saxo_session(setting=conf(refresh=None),
                             access_provider=never).state == "LOGIN_REQUIRED"


def test_auth_failures_are_redacted_not_returned_as_secrets():
    def fail():
        raise SaxoAuthenticationError("refresh_token=SENSITIVE")
    status = keep_saxo_session(setting=conf(), access_provider=fail)
    assert status.state == "LOGIN_REQUIRED"
    assert "SENSITIVE" not in status.detail


def test_session_keeper_systemd_is_opt_in_and_secretless():
    unit = (ROOT / "deploy/systemd/christiania-saxo-session.service").read_text()
    timer = (ROOT / "deploy/systemd/christiania-saxo-session.timer").read_text()
    app = (ROOT / "deploy/systemd/christiania-app.service").read_text()
    activation = (ROOT / "deploy/activate_one_vm.sh").read_text()
    assert "User=christiania" in unit
    assert "ProtectSystem=strict" in unit
    assert "ReadWritePaths=-/var/lib/christiania/secure" in unit
    assert "CHRISTIANIA_SAXO_TOKEN_STORE=" in unit
    assert "SAXO_LIVE_REFRESH_TOKEN=" not in unit
    assert "ExecStart=/opt/christiania/.venv/bin/python -m src.operations.saxo_session_keeper_v1" in unit
    assert "OnUnitActiveSec=5min" in timer
    assert "christiania-saxo-session.timer" not in activation
    assert "ReadWritePaths=-/var/lib/christiania/secure" in app
