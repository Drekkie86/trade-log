from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_streamlit_native_sidebar_navigation_is_disabled() -> None:
    config = (ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8")

    assert "[client]" in config
    assert "showSidebarNavigation = false" in config


def test_operator_interface_has_only_one_visible_navigation_owner() -> None:
    """app.py owns production navigation; Streamlit must not add pages/*.py beside it."""
    config = (ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8")
    app = (ROOT / "app.py").read_text(encoding="utf-8")

    assert "showSidebarNavigation = false" in config
    assert "st.radio(" in app
