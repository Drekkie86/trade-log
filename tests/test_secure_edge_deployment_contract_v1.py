from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_public_caddy_edge_never_proxies_directly_to_streamlit():
    caddy = (ROOT / "deploy/secure-edge/Caddyfile.template").read_text(encoding="utf-8")
    assert "reverse_proxy 127.0.0.1:4180" in caddy
    assert "{{CHRISTIANIA_PUBLIC_HOST}}" in caddy
    assert "8501" not in caddy
    assert "Strict-Transport-Security" in caddy


def test_oauth_gateway_is_loopback_and_only_upstreams_to_loopback_streamlit():
    unit = (ROOT / "deploy/systemd/christiania-oauth2-proxy.service").read_text(encoding="utf-8")
    assert "OAUTH2_PROXY_HTTP_ADDRESS=127.0.0.1:4180" in unit
    assert "OAUTH2_PROXY_UPSTREAMS=http://127.0.0.1:8501/" in unit
    assert "0.0.0.0" not in unit
    assert "OAUTH2_PROXY_COOKIE_SECURE=true" in unit
    assert "OAUTH2_PROXY_COOKIE_HTTPONLY=true" in unit
    assert "OAUTH2_PROXY_COOKIE_NAME=__Host-christiania" in unit
    assert "EnvironmentFile=/etc/christiania/secure-edge.env" in unit
    assert "christiania.env" not in unit.replace("secure-edge.env", "")


def test_auth_gateway_has_explicit_restart_bounds_and_sandbox():
    unit = (ROOT / "deploy/systemd/christiania-oauth2-proxy.service").read_text(encoding="utf-8")
    for required in (
        "StartLimitIntervalSec=300",
        "StartLimitBurst=5",
        "Restart=on-failure",
        "NoNewPrivileges=true",
        "PrivateDevices=true",
        "ProtectSystem=strict",
        "ProtectHome=true",
        "RestrictSUIDSGID=true",
    ):
        assert required in unit


def test_streamlit_service_is_loopback_bounded_and_sandboxed():
    unit = (ROOT / "deploy/systemd/christiania-app.service").read_text(encoding="utf-8")
    assert "--host 127.0.0.1" in unit
    assert "StartLimitIntervalSec=300" in unit
    assert "StartLimitBurst=5" in unit
    assert "Restart=on-failure" in unit
    assert "ProtectSystem=strict" in unit


def test_secure_edge_installer_refuses_unmanaged_caddyfile_by_contract():
    script = (ROOT / "deploy/install_secure_edge.sh").read_text(encoding="utf-8")
    assert "Refusing to overwrite an unmanaged" in script
    assert "Nothing was enabled or started automatically" in script


def test_secure_edge_remove_preserves_identity_configuration():
    script = (ROOT / "deploy/remove_secure_edge.sh").read_text(encoding="utf-8")
    assert "authorized_emails.txt were preserved" in script
    assert "christiania.env" not in "\n".join(line for line in script.splitlines() if line.strip().startswith("rm "))


def test_caddy_does_not_inherit_christiania_secret_environment():
    installer = (ROOT / "deploy/install_secure_edge.sh").read_text(encoding="utf-8")
    assert "caddy.service.d" not in installer
    assert "EnvironmentFile=/etc/christiania/christiania.env" not in installer
    assert "render_caddyfile" in installer


def test_deployment_separates_research_and_oidc_secret_files():
    core = (ROOT / "deploy/christiania.env.example").read_text(encoding="utf-8")
    edge = (ROOT / "deploy/secure-edge.env.example").read_text(encoding="utf-8")
    assert "MASSIVE_API_KEY" in core and "THETADATA_API_KEY" in core
    assert "OAUTH2_PROXY_CLIENT_SECRET" not in core
    assert "OAUTH2_PROXY_CLIENT_SECRET" in edge
    assert "MASSIVE_API_KEY" not in edge and "THETADATA_API_KEY" not in edge
