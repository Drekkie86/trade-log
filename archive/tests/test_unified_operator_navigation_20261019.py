"""Operator navigation and research/casino separation regression, 19 Oct 2026."""
from pathlib import Path

from streamlit.testing.v1 import AppTest

from tests.test_trade_ideas import seed_scenario

ROOT = Path(__file__).resolve().parents[1]


def test_operator_nav_shows_core_workflows_once(db_path, monkeypatch):
    import streamlit as st

    seed_scenario(db_path, with_v2=True)
    monkeypatch.setenv("CHRISTIANIA_DB_PATH", str(db_path))
    st.cache_data.clear()
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=90)
    app.run(timeout=90)
    assert not app.exception, app.exception
    assert app.sidebar.radio[0].options == [
        "💰 Trade Desk", "📈 Performance", "🩺 System",
        "🧰 Advanced tools",
    ]
    assert app.sidebar.radio[0].value == "💰 Trade Desk"
    assert any("NO TRADE" in x.value for x in app.warning)
    assert not any(m.label == "Resolved expiry outcomes" for m in app.metric)

    # The performance surface is an outcome accountability page, not a
    # parallel candidate recommender or a wall of legacy research tables.
    app.sidebar.radio[0].set_value("📈 Performance").run(timeout=90)
    assert not app.exception, app.exception
    assert any(m.label == "Verified realized net profit" for m in app.metric)

    # All historic tooling remains traceable behind diagnostics only.
    app.sidebar.radio[0].set_value("🧰 Advanced tools").run(timeout=90)
    assert not app.exception, app.exception
    tools = app.sidebar.selectbox[0].options
    assert "Trade Ideas" in tools
    assert "Shadow Lab" in tools
    assert "Storm Cellar / 0DTE Lab" in tools

    app.sidebar.selectbox[0].set_value("Storm Cellar / 0DTE Lab").run(timeout=90)
    assert not app.exception, app.exception
    assert any("NO CASINO TRADE" in i.value for i in app.info)
    assert any(t.label == "Explore 0DTE research and scenarios" for t in app.get("toggle"))

    app.sidebar.selectbox[0].set_value("Shadow Lab").run(timeout=90)
    assert not app.exception, app.exception
    assert any(m.label == "Resolved expiry outcomes" for m in app.metric)


def test_casino_legacy_page_uses_same_renderer():
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    legacy = (ROOT / "pages/06_Casino_0DTE_Lab.py").read_text(encoding="utf-8")
    renderer = (ROOT / "src/ui/casino_page.py").read_text(encoding="utf-8")
    assert 'elif page == "Storm Cellar / 0DTE Lab":\n    render_casino_page()' in app
    assert "render_casino_page()" in legacy
    assert "evaluate_casino_experiment(" in renderer
    assert "NO CASINO TRADE" in renderer
    assert "NO CRYING IN THE CASINO" not in renderer
    assert "load_casino_0dte_runtime()" in renderer
