from pathlib import Path


def test_systemd_daemon_waits_for_theta_api():
    text = Path(
        "deploy/systemd/christiania-daemon.service"
    ).read_text(encoding="utf-8")

    assert "Requires=christiania-theta.service" in text
    assert "ExecStartPre=" in text
    assert "run_theta_probe.py --wait-seconds 180" in text


def test_cloud_health_requires_theta_and_daemon():
    text = Path(
        "deploy/systemd/christiania-health.service"
    ).read_text(encoding="utf-8")

    assert "--strict-daemon" in text
    assert "--strict-theta" in text


def test_control_plane_has_no_broker_order_path():
    combined = "\n".join(
        Path(path).read_text(encoding="utf-8").lower()
        for path in (
            "src/providers/thetadata_control.py",
            "run_theta_probe.py",
        )
    )

    for token in (
        "place_order",
        "submit_order",
        "create_order",
        "saxo",
    ):
        assert token not in combined


def test_readiness_does_not_claim_live_timestamp_validation():
    text = Path(
        "src/providers/thetadata_control.py"
    ).read_text(encoding="utf-8")

    assert "DOCUMENTED_AND_LIVE_VALIDATED" not in text


def test_all_research_launchers_share_managed_theta_control_plane():
    launchers = (
        "run_christiania_research.py",
        "run_christiania_cycle.py",
        "run_christiania_full_cycle.py",
    )

    for launcher in launchers:
        text = Path(launcher).read_text(encoding="utf-8")
        assert "configured_theta_client" in text
        assert "probe_theta_terminal" in text
        assert "ThetaDataClient()" not in text
