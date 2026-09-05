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
        '"Storm Cellar / 0DTE Lab"',
        '"Ops"',
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

    assert "Speculative by charter, quantitative by discipline" in app
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
    assert "Storm Cellar / 0DTE Lab" in doc
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
    assert "padding-top: 5.75rem" in theme


def test_sidebar_uses_new_motto_and_removes_old_quote():
    app = (ROOT / "app.py").read_text(encoding="utf-8")

    assert "NO CRYING IN THE CASINO" in app
    assert "BETTER QUESTIONS" not in app
    assert "LEAD TO CALMER SEAS" not in app


def test_tables_use_human_readable_column_labels():
    app = (ROOT / "app.py").read_text(encoding="utf-8")

    assert '"scheduled_for": "Scheduled for"' in app
    assert '"research_run_id": "Research run ID"' in app
    assert '"outcome_mark_count": "Marks this cycle"' in app
    assert "_humanize_dataframe" in app
    assert "_show_table(" in app


def test_shadow_lab_exposes_followup_and_measurement_semantics():
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    read_model = (ROOT / "src/dashboard/read_model.py").read_text(encoding="utf-8")

    assert "Candidate lifecycle" in app
    assert "Validated outcomes" in app
    assert "liquidation stress marks" in app
    assert "shadow_mark_history" in read_model
    assert "shadow_candidate_followup" in read_model
    assert "outcome_eligible" in read_model


def test_global_header_copy_is_minimal_and_not_patronizing():
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    components = (ROOT / "src/ui/components.py").read_text(encoding="utf-8")

    assert "V1 Research Workstation" not in components
    assert "one disciplined deck" not in app
    assert "Surfaced anomalies and model disagreement are not trade signals" not in components
    assert "<div class=\"chr-hero-title\">CHRISTIANIA</div>" in components


def test_shadow_lab_separates_thesis_and_validated_trade_result():
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    read_model = (ROOT / "src/dashboard/read_model.py").read_text(encoding="utf-8")

    assert "Thesis assessment" in app
    assert "Validated trade result" in app
    assert "Christiania does not infer thesis correctness from a profitable mark" in app
    assert "validated_trade_result" in read_model
    assert "thesis_assessment" in read_model
    assert "outcome_eligible = 1" in read_model


def test_dataframe_humanizer_uses_real_dict_not_set_literal():
    app = (ROOT / "app.py").read_text(encoding="utf-8")

    assert "labels = {{" not in app
    assert "labels = {" in app


def test_ui_exports_and_app_imports_resolve_structurally():
    import ast

    components_tree = ast.parse(
        (ROOT / "src" / "ui" / "components.py").read_text(encoding="utf-8")
    )
    component_symbols = {
        node.name
        for node in components_tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }

    init_tree = ast.parse(
        (ROOT / "src" / "ui" / "__init__.py").read_text(encoding="utf-8")
    )
    component_exports = set()
    ui_exports = set()
    for node in init_tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "components":
            component_exports.update(alias.asname or alias.name for alias in node.names)
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "__all__":
                    if isinstance(node.value, (ast.List, ast.Tuple)):
                        ui_exports.update(
                            elt.value
                            for elt in node.value.elts
                            if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                        )

    assert component_exports <= component_symbols

    app_tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
    app_ui_imports = set()
    for node in app_tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "src.ui":
            app_ui_imports.update(alias.asname or alias.name for alias in node.names)

    # __all__ is only part of the export surface; additionally account for semantics imports.
    bound_names = set()
    for node in init_tree.body:
        if isinstance(node, ast.ImportFrom):
            bound_names.update(alias.asname or alias.name for alias in node.names)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound_names.add(node.name)

    assert app_ui_imports <= bound_names
    assert "observation_banner" not in app_ui_imports
    assert "observation_banner" not in component_exports


def test_table_helper_omits_none_height_and_uses_streamlit_width_contract():
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    assert 'dataframe_kwargs = {' in app
    assert '"width": "stretch"' in app
    assert 'if height is not None:' in app
    assert 'dataframe_kwargs["height"] = height' in app
    assert 'height=height' not in app
    helper = app.split("def _show_table(", 1)[1].split("st.set_page_config", 1)[0]
    assert 'use_container_width=True' not in helper


def test_table_helpers_keep_static_and_selectable_dataframe_calls_separate():
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    static_helper = app.split("def _show_table(", 1)[1].split("def _show_selectable_table(", 1)[0]
    selectable_helper = app.split("def _show_selectable_table(", 1)[1].split("st.set_page_config", 1)[0]
    assert static_helper.count("st.dataframe(") == 1
    assert "st.dataframe(frame, **dataframe_kwargs)" in static_helper
    assert selectable_helper.count("st.dataframe(") == 1
    assert '"on_select": "rerun"' in selectable_helper
    assert '"selection_mode": "single-row"' in selectable_helper


def test_dashboard_market_clock_uses_real_backend_contract_keys():
    app = (ROOT / "app.py").read_text(encoding="utf-8")

    assert 'market_clock.get("next_sample_at")' in app
    assert '(market_clock.get("session") or {}).get("session_date")' in app
    assert 'market_clock.get("next_sample")' not in app
    assert 'market_clock.get("session_date")' not in app


def test_compact_tables_expose_full_long_text():
    app = (ROOT / "app.py").read_text(encoding="utf-8")

    assert "_show_full_text_details" in app
    assert "Full text / identifiers" in app
    assert "complete stored values" in app
    assert '"Admission label"' in app


def test_ops_navigation_is_consolidated():
    app = (ROOT / "app.py").read_text(encoding="utf-8")

    assert '"⚙ Ops"' in app
    assert '["Readiness", "Release", "System"]' in app
    assert '"✓ Readiness"' not in app
    assert '"◆ Release Status"' not in app


def test_speculative_lab_name_does_not_brand_feature_as_casino():
    app = (ROOT / "app.py").read_text(encoding="utf-8")

    assert "Storm Cellar / 0DTE Lab" in app
    assert "<h3>🎲 Casino / 0DTE Lab" not in app
    assert "Casino in spirit, quant in discipline" not in app
    # The intentionally retained sidebar motto is branding, not the feature name.
    assert "NO CRYING IN THE CASINO" in app


def test_ops_failure_counts_have_warning_semantics():
    app = (ROOT / "app.py").read_text(encoding="utf-8")

    assert '"Failed / orphaned"' in app
    assert '"Underlying failures"' in app
    assert 'badge_tone="warn" if failed_or_orphaned else "good"' in app
    assert 'badge_tone="warn" if underlying_failures else "good"' in app


def test_theta_latency_is_rounded_and_localized_for_operator_display():
    app = (ROOT / "app.py").read_text(encoding="utf-8")

    assert "def _fmt_latency_ms" in app
    assert '_fmt_number(float(value), decimals=1)' in app
    assert 'round(float(theta_display["latency_ms"]), 1)' in app


def test_ui_source_has_no_accidental_dict_inside_set_literals():
    app = (ROOT / "app.py").read_text(encoding="utf-8")

    assert "{{" not in app
    assert "}}" not in app


def test_streamlit_width_api_is_current():
    app = (ROOT / "app.py").read_text(encoding="utf-8")

    assert "use_container_width" not in app
    assert 'width="stretch"' in app


def test_human_number_formatting_uses_belgian_readability_contract():
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "def _fmt_number" in app
    assert 'replace(",", "§").replace(".", ",").replace("§", ".")' in app
    assert '_fmt_count(prospective["observation_rows"])' in app
    assert '_fmt_number(theta_health.get("latency_ms")' not in app  # latency delegates centrally


def test_research_visuals_have_explanatory_microcopy():
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "How much evidence Christiania has collected" in app
    assert "A surfaced observation is a question to investigate" in app
    assert "Thesis assessment asks whether the original market idea was right" in app
    assert "This is the pre-flight checklist for the product" in app


def test_observations_support_view_only_cross_filtering():
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "_chr_observation_filters" in app
    assert "_show_observation_filter_strip" in app
    assert 'key="observations_selectable_table"' in app
    assert "st.vega_lite_chart(" in app
    assert '"name": "observation_pick"' in app
    assert 'on_select="rerun"' in app
    assert 'selection_mode="observation_pick"' in app
    assert "Clear filters" in app


def test_research_run_selection_can_focus_failure_diagnostics():
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    assert 'key="research_runs_selectable"' in app
    assert 'selected_run.get("research_run_id")' in app
    assert "Filtered to research run" in app


def test_interaction_layer_has_no_external_javascript_or_trade_mutation_words():
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    block = app.split('elif page == "Observations":', 1)[1].split('elif page == "Shadow Lab":', 1)[0]
    assert "javascript" not in block.lower()
    assert "submit_order" not in block
    assert "place_order" not in block
    assert "admission_enabled =" not in block
    assert "decision_enabled =" not in block
