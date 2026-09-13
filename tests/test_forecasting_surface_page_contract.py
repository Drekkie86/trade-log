from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_forecasting_surface_page_is_research_only() -> None:
    page = (ROOT / "pages/02_Forecasting_Surface_Intelligence.py").read_text(encoding="utf-8")
    assert "Forecasting & Surface Intelligence" in page
    assert "Decision authority" in page
    assert "Research-only" in page
    assert "load_forecast_surface_runtime" in page
