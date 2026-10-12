"""The actual Christiania main sidebar must expose the Stage-0 workbench."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def test_main_shadow_navigation_wires_stage0_near_top():
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    ast.parse(source)
    shadow_start = source.index('elif page == "Shadow Lab":')
    quant_start = source.index('elif page == "Quant Models":', shadow_start)
    shadow = source[shadow_start:quant_start]
    assert "render_shadow_stage0_workbench()" in shadow
    assert shadow.index("render_shadow_stage0_workbench()") < shadow.index("Evidence integrity")
    calibration_start = source.index('elif page == "Calibration":')
    assert "render_shadow_stage0_workbench()" not in source[calibration_start:shadow_start]

def test_legacy_and_main_share_single_workbench_implementation():
    legacy = (ROOT / "pages/04_Calibration_Shadow.py").read_text(encoding="utf-8")
    helper = (ROOT / "src/ui/shadow_stage0_workbench_v1.py").read_text(encoding="utf-8")
    ast.parse(legacy)
    ast.parse(helper)
    assert legacy.count("render_shadow_stage0_workbench()") == 1
    assert "def render_shadow_stage0_workbench()" in helper
    assert 'expanded=True' in helper
    assert "hypothetical_scenario" in helper
    assert "No broker strategy fill" in helper
    assert "st.form_submit_button" in helper
    assert not any(s in helper for s in ("place_order(", "submit_order(", "sqlite3.connect("))
