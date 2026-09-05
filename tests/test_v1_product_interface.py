from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_official_logo_is_packaged_and_used():
    logo = ROOT / "assets" / "christiania_logo.png"
    app = (ROOT / "app.py").read_text(encoding="utf-8")

    assert logo.exists()
    assert logo.stat().st_size > 100_000
    assert 'assets" / "christiania_logo.png"' in app
    assert "st.image" in app


def test_product_interface_information_architecture_is_explicit():
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    for label in [
        '"Dashboard"',
        '"Research Runs"',
        '"Calibration"',
        '"Observations"',
        '"Shadow Lab"',
        '"Quant Models"',
        '"Casino / 0DTE Lab"',
        '"Readiness"',
        '"Release Status"',
        '"System"',
    ]:
        assert label in app


def test_ui_keeps_scientific_and_execution_firewalls_visible():
    app = (ROOT / "app.py").read_text(encoding="utf-8")

    assert "OBSERVATIONAL ONLY" in app
    assert "not trade signals" in app
    assert "No broker-order path" in app
    assert "RESEARCH ONLY" in app
    assert "NOT PART OF CORE ENGINE" in app
    assert "NO TRADE" in app


def test_casino_is_visually_and_textually_separate():
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    theme = (ROOT / "src/ui/theme.py").read_text(encoding="utf-8")

    assert "Casino in spirit, quant in discipline" in app
    assert "TINY / CAPPED" in app
    assert "defined risk" in app
    assert ".chr-casino" in theme
    assert "--chr-red" in theme


def test_ui_theme_has_no_external_web_dependency():
    theme = (ROOT / "src/ui/theme.py").read_text(encoding="utf-8").lower()

    assert "http://" not in theme
    assert "https://" not in theme
    assert "@import" not in theme
    assert "#031522" in theme
    assert "#d9a84e" in theme


def test_pandas_is_declared_explicitly():
    for rel in ["requirements.txt", "requirements-ci.txt"]:
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert "pandas>=2.2,<3" in text


def test_ui_helpers_compile_as_standalone_modules():
    for rel in [
        "src/ui/__init__.py",
        "src/ui/theme.py",
        "src/ui/components.py",
    ]:
        assert (ROOT / rel).exists()


def test_product_interface_doc_tracks_current_navigation():
    doc = (ROOT / "docs/ui/V1_PRODUCT_INTERFACE.md").read_text(encoding="utf-8")
    assert "Package 9" in doc
    assert "Casino / 0DTE Lab" in doc
    assert "Product readiness and scientific maturity" in doc
    assert "authoritative product logo" in doc


def test_streamlit_theme_matches_product_palette():
    text = (ROOT / ".streamlit/config.toml").read_text(encoding="utf-8")
    assert 'primaryColor = "#D9A84E"' in text
    assert 'backgroundColor = "#031522"' in text
    assert 'secondaryBackgroundColor = "#08283E"' in text


def test_ui_polish_keeps_navigation_fast_and_explanatory():
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    components = (ROOT / "src/ui/components.py").read_text(encoding="utf-8")
    theme = (ROOT / "src/ui/theme.py").read_text(encoding="utf-8")

    assert "st.session_state" in app
    assert "RUNTIME_REFRESH_SECONDS = 180" in app
    assert "chart_note(" in app
    assert "chr-chart-note" in theme
    assert "padding-top: 4.75rem" in theme


def test_sidebar_uses_new_motto_and_removes_old_quote():
    app = (ROOT / "app.py").read_text(encoding="utf-8")

    assert "NO CRYING IN THE CASINO" in app
    assert "BETTER QUESTIONS" not in app
    assert "LEAD TO CALMER SEAS" not in app


def test_tables_use_human_readable_column_labels():
    app = (ROOT / "app.py").read_text(encoding="utf-8")

    assert '"scheduled_for": "Scheduled for"' in app
    assert '"research_run_id": "Research run ID"' in app
    assert '"outcome_mark_count": "Shadow marks"' in app
    assert "_humanize_dataframe" in app
    assert "_show_table(" in app


def test_shadow_lab_exposes_followup_and_measurement_semantics():
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    read_model = (ROOT / "src/dashboard/read_model.py").read_text(encoding="utf-8")

    assert "Candidate tracking over time" in app
    assert "Validated outcomes" in app
    assert "liquidation stress marks" in app
    assert "shadow_mark_history" in read_model
    assert "shadow_candidate_followup" in read_model
    assert "outcome_eligible" in read_model
