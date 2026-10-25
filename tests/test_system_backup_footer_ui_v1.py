"""End-to-end UI regression for the misleading backup red banner / stale label."""
from pathlib import Path

import streamlit as st
from streamlit.testing.v1 import AppTest

from src.operations.backup_system_status_v1 import BackupSystemStatus
from tests.test_trade_ideas import seed_scenario

ROOT=Path(__file__).resolve().parents[1]
COMMIT="cbcdd24b3371ef5e9a1c0af61077971e111072ef"


def test_system_uses_supervisor_restore_evidence_and_shows_release_sha(
    db_path,monkeypatch,
):
    seed_scenario(db_path,with_v2=True)
    monkeypatch.setenv("CHRISTIANIA_DB_PATH",str(db_path))
    monkeypatch.setenv("CHRISTIANIA_DISABLE_LOCAL_ENV_FALLBACK","1")
    monkeypatch.delenv("CHRISTIANIA_SAXO_TOKEN_STORE",raising=False)
    monkeypatch.setattr(
        "src.operations.backup_system_status_v1.read_backup_system_status",
        lambda: BackupSystemStatus(
            "VERIFIED",
            "Recovery point: schema v37. Independent full-restore audit PASSED.",
        ),
    )
    monkeypatch.setattr(
        "src.operations.release_manifest.read_deployed_commit",
        lambda: COMMIT,
    )
    st.cache_data.clear()
    app=AppTest.from_file(str(ROOT/"app.py"),default_timeout=90)
    app.run(timeout=90)
    system=next(x for x in app.sidebar.radio[0].options if x.endswith("System"))
    app.sidebar.radio[0].set_value(system).run(timeout=90)
    assert not app.exception,app.exception
    content=" ".join(
        [str(x.value) for x in app.markdown]
        + [str(x.value) for x in app.caption]
    )
    assert "Independent full-restore audit PASSED" in content
    assert "No valid backup found" not in content
    footer=" ".join(str(x.value) for x in app.sidebar.caption)
    assert "cbcdd24" in footer
    assert "schema v" in footer
    assert "1.0.0-rc1" not in footer
