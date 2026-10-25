"""Saxo is visible on System, never an implicit order or data entitlement."""
from pathlib import Path

import streamlit as st
from streamlit.testing.v1 import AppTest

from tests.test_trade_ideas import seed_scenario

ROOT = Path(__file__).resolve().parents[1]


def test_saxo_connection_appears_in_system_health_without_credentials(db_path, monkeypatch):
    seed_scenario(db_path, with_v2=True)
    monkeypatch.setenv("CHRISTIANIA_DB_PATH", str(db_path))
    monkeypatch.setenv("CHRISTIANIA_DISABLE_LOCAL_ENV_FALLBACK", "1")
    monkeypatch.delenv("CHRISTIANIA_SAXO_TOKEN_STORE", raising=False)
    monkeypatch.delenv("SAXO_LIVE_APP_KEY", raising=False)
    st.cache_data.clear()

    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=90)
    app.run(timeout=90)
    system = next(x for x in app.sidebar.radio[0].options if x.endswith("System"))
    app.sidebar.radio[0].set_value(system).run(timeout=90)
    assert not app.exception, app.exception

    everything = " ".join(
        [str(x.value) for x in app.markdown]
        + [str(x.value) for x in app.caption]
        + [str(x.value) for x in app.info]
        + [str(x.value) for x in app.warning]
    )
    assert "Saxo LIVE" in everything
    assert "Saxo market data" in everything
    assert "Not connected" in everything
    assert "not yet verified" in everything
    # Health may not leak any bearer tokens or app-key material.
    assert "SAXO_LIVE_REFRESH_TOKEN" not in everything
