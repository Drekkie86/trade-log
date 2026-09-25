from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

PAGES = (
    "01_Research_Command_Deck.py",
    "02_Forecasting_Surface_Intelligence.py",
    "03_Edge_Risk_Lab.py",
    "04_Calibration_Shadow.py",
    "05_Decision_Discipline.py",
    "06_Casino_0DTE_Lab.py",
)


def _page(name: str) -> str:
    return (
        ROOT
        / "pages"
        / name
    ).read_text(
        encoding="utf-8"
    )


def test_all_research_pages_cache_runtime_reads_for_180_seconds():
    for name in PAGES:
        text = _page(name)
        assert "@st.cache_data(ttl=180, show_spinner=False)" in text
        assert text.index("st.set_page_config(") < text.index("@st.cache_data(")


def test_heavy_forecast_and_edge_pages_route_runtime_through_cache():
    forecast = _page(
        "02_Forecasting_Surface_Intelligence.py"
    )
    edge = _page(
        "03_Edge_Risk_Lab.py"
    )

    assert "state = _cached_forecast_surface_runtime(" in forecast
    assert "state = load_forecast_surface_runtime(" not in forecast

    assert "runtime = _cached_edge_risk_runtime(" in edge
    assert "runtime = load_edge_risk_runtime(" not in edge


def test_manual_refresh_clears_cached_runtime_before_rerun():
    command = _page(
        "01_Research_Command_Deck.py"
    )
    forecast = _page(
        "02_Forecasting_Surface_Intelligence.py"
    )

    assert "_cached_research_command_deck.clear()" in command
    assert "_cached_forecast_surface_runtime.clear()" in forecast
