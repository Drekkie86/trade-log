from __future__ import annotations

from src.operations.boot_identity import BootMarker, current_boot_id, read_boot_marker, reboot_proven, write_boot_marker


def test_boot_marker_roundtrip_and_reboot_proof(tmp_path):
    path = tmp_path / "marker.json"
    marker = write_boot_marker(path, boot_id="boot-before")
    assert read_boot_marker(path) == marker
    assert reboot_proven(marker, current="boot-after") is True
    assert reboot_proven(marker, current="boot-before") is False


def test_unavailable_fallback_never_counts_as_reboot():
    marker = BootMarker("UNAVAILABLE:one", "2026-09-05T00:00:00+00:00")
    assert reboot_proven(marker, current="UNAVAILABLE:two") is False


def test_boot_id_override_is_deterministic(monkeypatch):
    monkeypatch.setenv("CHRISTIANIA_BOOT_ID_OVERRIDE", "test-boot")
    assert current_boot_id() == "test-boot"
