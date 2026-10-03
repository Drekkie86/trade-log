"""Behavioral test: opening Ops must never trigger O(database-size) work.

Executes the real app.py with Streamlit's AppTest and records calls at the
two expensive boundaries: deep PRAGMA integrity checks on the live database
and full verification of every backup. Neither may run until the operator
explicitly requests deep verification.
"""
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("streamlit.testing.v1")
from streamlit.testing.v1 import AppTest

import src.dashboard.read_model as read_model
import src.operations.backup_recovery as backup_recovery
import src.providers.thetadata_control as thetadata_control

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def recorded(db_path, tmp_path, monkeypatch):
    monkeypatch.setenv("CHRISTIANIA_DB_PATH", str(db_path))
    monkeypatch.setenv("CHRISTIANIA_BACKUP_DIR", str(tmp_path / "backups"))
    (tmp_path / "backups").mkdir()
    calls = {"deep_integrity": 0, "deep_backup_inventory": 0}

    real_inspect = read_model.inspect_database

    def inspect_spy(path, *, deep_integrity=True):
        if deep_integrity:
            calls["deep_integrity"] += 1
        return real_inspect(path, deep_integrity=deep_integrity)

    real_inventory = backup_recovery.inventory_backups

    def inventory_spy(*args, **kwargs):
        calls["deep_backup_inventory"] += 1
        return real_inventory(*args, **kwargs)

    monkeypatch.setattr(read_model, "inspect_database", inspect_spy)
    monkeypatch.setattr(backup_recovery, "inventory_backups", inventory_spy)

    class _ThetaDown:
        def as_dict(self):
            return {"state": "NOT_PROBED", "ready": False, "detail": "test"}

    monkeypatch.setattr(thetadata_control, "probe_theta_terminal", lambda *a, **k: _ThetaDown())
    monkeypatch.setattr(read_model, "probe_theta_terminal", lambda *a, **k: _ThetaDown())
    return calls


def _open_ops(app):
    app.run(timeout=60)
    app.sidebar.radio[0].set_value("⚙ Ops").run(timeout=60)
    return app


def test_opening_ops_does_not_run_deep_verification(recorded, monkeypatch):
    import app as _  # noqa: F401  (ensures patched modules are the ones imported)
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
    # app.py imports inventory_backups by name; patch that binding too.
    _open_ops(app)
    assert not app.exception, app.exception
    assert recorded["deep_integrity"] == 0
    assert recorded["deep_backup_inventory"] == 0
    labels = [b.label for b in app.button]
    assert "Run deep verification" in labels


def test_deep_verification_runs_only_after_explicit_request(recorded):
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
    _open_ops(app)
    assert recorded["deep_integrity"] == 0
    button = next(b for b in app.button if b.label == "Run deep verification")
    button.click().run(timeout=60)
    assert not app.exception, app.exception
    assert recorded["deep_integrity"] >= 1
    assert recorded["deep_backup_inventory"] >= 1


ANOMALIES = [
    {"underlying": u, "surfaced_direction": d, "right": r, "expiration": "2026-12-18",
     "strike": 100.0 + i, "iv_residual": 0.03, "abs_iv_residual": 0.03 + i / 1000,
     "evaluated_at": "2026-09-30T15:00:00Z"}
    for i, (u, d, r) in enumerate([
        ("COIN", "IV_RICH_LOCAL", "C"), ("SPY", "IV_CHEAP_LOCAL", "P"),
        ("COIN", "IV_RICH_LOCAL", "P"), ("AMD", "IV_RICH_LOCAL", "C"),
    ])
]


def test_clear_observation_filters_clears_state_without_crashing(recorded, monkeypatch):
    # Limitation: AppTest runs fragment interactions as full script runs, so it
    # cannot observe rerun *scope*. This test proves the button clears filters
    # and cannot raise (it fails for st.rerun(scope="fragment") here). The
    # no-whole-app-rerun property rests on on_click containing no st.rerun().
    real_loader = read_model.load_command_deck

    def loader_with_anomalies(*args, **kwargs):
        deck = real_loader(*args, **kwargs)
        deck["recent_anomalies"] = [dict(row) for row in ANOMALIES]
        return deck

    monkeypatch.setattr(read_model, "load_command_deck", loader_with_anomalies)
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
    app.run(timeout=60)
    app.sidebar.radio[0].set_value("◉ Observations").run(timeout=60)
    app.session_state["_chr_observation_filters"] = {"underlying": "COIN"}
    app.run(timeout=60)
    clear = [b for b in app.button if b.label == "Clear filters"]
    assert clear, "filter strip should render when a filter is active"
    clear[0].click().run(timeout=60)
    assert not app.exception, app.exception
    assert app.session_state["_chr_observation_filters"] == {}
