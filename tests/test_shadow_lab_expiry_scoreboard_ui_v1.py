"""The real app renders the expiry scoreboard on Dashboard and Shadow Lab."""
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("streamlit.testing.v1")
from streamlit.testing.v1 import AppTest

import src.dashboard.read_model as read_model
import src.providers.thetadata_control as thetadata_control
from src.database.repository import get_connection
from src.research.shadow_expiry_outcome_v1 import record_shadow_expiry_outcomes
from tests.test_shadow_expiry_outcome_v1 import _insert_run, _insert_snapshot
from tests.test_shadow_outcome_collector import seed_active_candidate

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def app_db(db_path, tmp_path, monkeypatch):
    monkeypatch.setenv("CHRISTIANIA_DB_PATH", str(db_path))
    monkeypatch.setenv("CHRISTIANIA_BACKUP_DIR", str(tmp_path / "backups"))
    (tmp_path / "backups").mkdir()

    class _ThetaDown:
        def as_dict(self):
            return {"state": "NOT_PROBED", "ready": False, "detail": "test"}

    monkeypatch.setattr(thetadata_control, "probe_theta_terminal", lambda *a, **k: _ThetaDown())
    monkeypatch.setattr(read_model, "probe_theta_terminal", lambda *a, **k: _ThetaDown())
    # app.py caches page snapshots per page name (one DB in production); tests
    # swap databases between runs, so drop every cache_data entry first.
    import streamlit as st
    st.cache_data.clear()
    return db_path


def _open_advanced(app, tool):
    """Old pages now live under Advanced tools."""
    if not app.sidebar.selectbox:
        app.sidebar.radio[0].set_value("🧰 Advanced tools").run(timeout=60)
    app.sidebar.selectbox[0].set_value(tool).run(timeout=60)


def _metric_labels(app):
    return {m.label: (m.value, m.delta) for m in app.metric}


def test_empty_database_renders_zero_outcomes(app_db):
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
    app.run(timeout=60)  # opens on Trade Ideas, the default page
    _open_advanced(app, "Dashboard")
    assert not app.exception, app.exception
    metrics = _metric_labels(app)
    assert metrics["Expiry outcomes"][0] == "0"

    _open_advanced(app, "Shadow Lab")
    assert not app.exception, app.exception
    metrics = _metric_labels(app)
    assert metrics["Resolved expiry outcomes"][0] == "0"
    assert metrics["Win rate"][0] == "—"
    assert any("No expired candidate has a resolved modeled outcome yet" in i.value for i in app.info)


def test_resolved_outcome_shows_on_both_pages(app_db):
    candidate_id, _ = seed_active_candidate(app_db)
    conn = get_connection(app_db)
    try:
        expiry_run = _insert_run(conn, started="2026-09-18T19:45:00Z", session_date="2026-09-18")
        _insert_snapshot(conn, run_id=expiry_run, captured_at="2026-09-18T19:45:00Z",
                         session_date="2026-09-18", price=108.0)
        after = _insert_run(conn, started="2026-09-21T14:00:00Z", session_date="2026-09-21")
        conn.commit()
    finally:
        conn.close()
    record_shadow_expiry_outcomes(research_run_id=after, db_path=app_db)

    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
    app.run(timeout=60)  # opens on Trade Ideas, the default page
    _open_advanced(app, "Dashboard")
    assert not app.exception, app.exception
    value, delta = _metric_labels(app)["Expiry outcomes"]
    assert value == "1"
    assert "100% modeled-positive" in delta

    _open_advanced(app, "Shadow Lab")
    assert not app.exception, app.exception
    metrics = _metric_labels(app)
    assert metrics["Resolved expiry outcomes"][0] == "1"
    assert metrics["Win rate"][0] == "100%"
    assert metrics["Modeled net value at expiry"][0].startswith("€")
    assert metrics["Net / defined risk"][0] == "+294.0%"
    assert metrics["Result at expiry"][0] == "MODELED POSITIVE AT EXPIRY"
    assert any("not official settlement or closing prices" in w.value for w in app.warning)


def test_results_and_system_pages_render(app_db):
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
    app.run(timeout=60)
    app.sidebar.radio[0].set_value("📈 Results").run(timeout=60)
    assert not app.exception, app.exception
    assert "Ideas found" in _metric_labels(app)
    app.sidebar.radio[0].set_value("🩺 System").run(timeout=60)
    assert not app.exception, app.exception
