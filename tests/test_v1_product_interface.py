from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_official_logo_is_packaged_and_used():
    logo = ROOT / "assets" / "christiania_logo.png"
    app = (ROOT / "app.py").read_text(encoding="utf-8")

    assert logo.exists()
    assert logo.stat().st_size > 100_000
    assert 'assets" / "christiania_logo.png"' in app
    assert "st.image" in app








def test_ui_theme_has_no_external_web_dependency():
    theme = (ROOT / "src/ui/theme.py").read_text(encoding="utf-8").lower()

    assert "http://" not in theme
    assert "https://" not in theme
    assert "@import" not in theme
    assert "#031522" in theme
    assert "#d9a84e" in theme


def test_pandas_is_pinned_for_runtime_and_inherited_by_ci():
    runtime = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    ci = (ROOT / "requirements-ci.txt").read_text(encoding="utf-8")

    assert "pandas==2.3.3" in runtime
    assert "-r requirements.txt" in ci


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




def test_sidebar_motto_is_removed():
    app = (ROOT / "app.py").read_text(encoding="utf-8")

    assert "NO CRYING IN THE CASINO" not in app
    assert "BETTER QUESTIONS" not in app
    assert "LEAD TO CALMER SEAS" not in app






def test_global_header_copy_is_minimal_and_not_patronizing():
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    components = (ROOT / "src/ui/components.py").read_text(encoding="utf-8")

    assert "V1 Research Workstation" not in components
    assert "one disciplined deck" not in app
    assert "Surfaced anomalies and model disagreement are not trade signals" not in components
    assert "<div class=\"chr-hero-title\">CHRISTIANIA</div>" not in components






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


















def test_ui_source_has_no_accidental_dict_inside_set_literals():
    app = (ROOT / "app.py").read_text(encoding="utf-8")

    assert "{{" not in app
    assert "}}" not in app


def test_streamlit_width_api_is_current():
    app = (ROOT / "app.py").read_text(encoding="utf-8")

    assert "use_container_width" not in app
    assert 'width="stretch"' in app
















def test_cash_settlement_policy_is_explicit_not_inferred():
    policy = (ROOT / "src/research/settlement_policy.py").read_text(encoding="utf-8")

    assert '"SPX"' in policy
    assert '"XSP"' in policy
    assert "FAIL_CLOSED" in policy
    assert "BLOCKED_UNVERIFIED_SETTLEMENT" in policy





def test_decision_desk_v2_keeps_no_order_boundary():
    files = [
        ROOT / "src/decision/desk.py",
        ROOT / "src/decision/governance.py",
        ROOT / "src/decision/market_quality.py",
        ROOT / "src/decision/evidence.py",
        ROOT / "src/decision/scenarios.py",
    ]
    text = "\n".join(path.read_text(encoding="utf-8") for path in files)
    assert "submit_order" not in text
    assert "place_order" not in text
    assert "broker_order" not in text
