from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_core_activation_starts_theta_before_daemon_and_waits_for_readiness():
    text = (ROOT / "deploy/activate_one_vm.sh").read_text(encoding="utf-8")
    assert text.index("christiania-theta.service") < text.index("christiania-daemon.service")
    assert "run_theta_probe.py\" --wait-seconds 180" in text
    assert "--strict-daemon --strict-theta --strict-backup" in text
    assert "christiania-burn-in.timer" in text


def test_secure_edge_activation_preflights_before_enabling_oauth_proxy():
    text = (ROOT / "deploy/activate_secure_edge.sh").read_text(encoding="utf-8")
    assert text.index("christiania_secure_edge_preflight.py") < text.index("systemctl enable --now christiania-oauth2-proxy.service")
    assert "caddy validate" in text
    assert "systemctl is-active --quiet caddy.service" in text


def test_release_receiver_prunes_only_after_successful_activation():
    text = (ROOT / "deploy/receive_release.sh").read_text(encoding="utf-8")
    prune = text.index("prune_christiania_releases.py")
    trap_clear = text.index("trap - ERR INT TERM HUP")
    activated = text.index('echo "CHRISTIANIA RELEASE ACTIVATED"')
    assert trap_clear < prune < activated
    assert "--retention 4" in text
    assert "WARNING: release-directory pruning failed; activation remains valid." in text
