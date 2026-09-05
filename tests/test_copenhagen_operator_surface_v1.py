from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_operator_cli_contains_expected_commands():
    text = (ROOT / "christiania_ops.py").read_text(encoding="utf-8")
    for command in ("status", "readiness", "backups", "backup", "restore-drill", "export", "copenhagen"):
        assert f'"{command}"' in text


def test_one_vm_installer_does_not_enable_services_automatically():
    text = (ROOT / "deploy/install_one_vm.sh").read_text(encoding="utf-8")
    assert "No services were enabled automatically" in text
    assert "systemctl enable" not in text
    assert "--exclude 'vendor/'" in text


def test_service_removal_preserves_data_and_secrets():
    text = (ROOT / "deploy/remove_one_vm_services.sh").read_text(encoding="utf-8")
    assert "/var/lib/christiania" not in text
    assert "/etc/christiania/christiania.env" not in text
    assert "intentionally left untouched" in text


def test_audit_and_restore_drill_timers_are_persistent():
    audit = (ROOT / "deploy/systemd/christiania-audit.timer").read_text(encoding="utf-8")
    restore = (ROOT / "deploy/systemd/christiania-restore-drill.timer").read_text(encoding="utf-8")
    assert "Persistent=true" in audit
    assert "Persistent=true" in restore


def test_copenhagen_docs_keep_science_separate_from_product_readiness():
    text = (ROOT / "docs/operations/V1_COPENHAGEN_READINESS.md").read_text(encoding="utf-8")
    assert "operational product readiness" in text.lower()
    assert "scientific evidence maturity" in text.lower()
    assert "No live broker-order path" in text
