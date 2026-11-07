"""Profit-first UI must replace, not duplicate, legacy research dashboards."""
from pathlib import Path

from streamlit.testing.v1 import AppTest

from tests.test_trade_ideas import seed_scenario

ROOT = Path(__file__).resolve().parents[1]


def test_default_profit_screen_has_no_legacy_dataframe_wall(db_path, monkeypatch):
    import streamlit as st

    seed_scenario(db_path, with_v2=True)
    monkeypatch.setenv("CHRISTIANIA_DB_PATH", str(db_path))
    st.cache_data.clear()
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=90)
    app.run(timeout=90)
    assert not app.exception, app.exception
    assert app.sidebar.radio[0].value == "💰 Trade Desk"
    assert app.dataframe == []
    assert any("NO TRADE" in item.value for item in app.warning)
    assert [m.label for m in app.metric][:4] == [
        "Trades clearing the complete gate",
        "Prospective decisions recorded",
        "Snapshots assessed for trade selection",
        "Qualified source prices",
    ]
    assert all(m.label not in {
        "Worth a look", "Marginal", "Skip", "Modeled proxy payoffs"
    } for m in app.metric)


def test_performance_does_not_invent_realized_money(db_path, monkeypatch):
    import streamlit as st

    seed_scenario(db_path, with_v2=True)
    monkeypatch.setenv("CHRISTIANIA_DB_PATH", str(db_path))
    st.cache_data.clear()
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=90)
    app.run(timeout=90)
    app.sidebar.radio[0].set_value("📈 Performance").run(timeout=90)
    assert not app.exception, app.exception
    metric = next(x for x in app.metric if x.label == "Verified realized net profit")
    assert metric.value == "Not available"
    assert all("Win rate" != x.label for x in app.metric)
    assert app.dataframe == []
