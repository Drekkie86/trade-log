from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_release_surface_contains_no_broker_execution_capability():
    targets = [
        ROOT / "christiania_release.py",
        ROOT / "src" / "operations" / "release_manifest.py",
        ROOT / "src" / "operations" / "release_acceptance.py",
        ROOT / "src" / "operations" / "burn_in.py",
        ROOT / "src" / "operations" / "boot_identity.py",
    ]
    forbidden = ["place_order(", "send_order(", "submit_order(", "execute_order(", "src.providers.saxo"]
    text = "\n".join(path.read_text(encoding="utf-8") for path in targets)
    for token in forbidden:
        assert token not in text


def test_release_candidate_does_not_change_schema_or_quant_governance():
    docs = (ROOT / "docs" / "release" / "V1_RELEASE_CANDIDATE_ACCEPTANCE.md").read_text(encoding="utf-8")
    assert "no model has decision/admission authority" in docs
    assert "scientific" in docs.lower()
    assert "72 hours" in docs


def test_version_is_explicit_rc_not_final_v1():
    text = (ROOT / "src" / "version.py").read_text(encoding="utf-8")
    assert 'CHRISTIANIA_VERSION = "1.0.0-rc1"' in text
    assert 'RELEASE_CHANNEL = "release-candidate"' in text
