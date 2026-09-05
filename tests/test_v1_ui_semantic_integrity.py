from pathlib import Path

import importlib.util

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "christiania_ui_semantics", ROOT / "src" / "ui" / "semantics.py"
)
assert SPEC is not None and SPEC.loader is not None
SEMANTICS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SEMANTICS)
calibration_evidence_state = SEMANTICS.calibration_evidence_state
hypothesis_label = SEMANTICS.hypothesis_label
model_label = SEMANTICS.model_label
provider_label = SEMANTICS.provider_label


def test_calibration_never_claims_ready_while_decisions_are_disabled_and_evidence_is_early():
    state = calibration_evidence_state(
        models=[{"decision_enabled": 0, "admission_enabled": 0}],
        hypotheses=[{"decision_enabled": 0}],
        independent_dates=1,
    )
    assert state["state"] == "DISCOVERY ONLY — NOT READY FOR DECISIONS"
    assert state["tone"] == "warn"


def test_calibration_review_threshold_does_not_enable_decisions():
    state = calibration_evidence_state(
        models=[{"decision_enabled": 0, "admission_enabled": 0}],
        hypotheses=[{"decision_enabled": 0}],
        independent_dates=25,
    )
    assert "DECISIONS STILL DISABLED" in state["state"]
    assert "READY" not in state["state"]


def test_governance_violation_fails_visibly_instead_of_looking_ready():
    state = calibration_evidence_state(
        models=[{"decision_enabled": 1, "admission_enabled": 0}],
        hypotheses=[],
        independent_dates=25,
    )
    assert state["tone"] == "bad"
    assert state["state"] == "GOVERNANCE REVIEW REQUIRED"


def test_friendly_aliases_are_one_to_one_and_unknown_values_remain_raw():
    assert hypothesis_label("H2_MODEL_FORM_GENERALIZATION") == "Model-form generalization"
    assert model_label("LOCAL_SURFACE_QUADRATIC_V2") == "Local surface quadratic residual"
    assert hypothesis_label("SOME_FUTURE_HYPOTHESIS_V9") == "SOME_FUTURE_HYPOTHESIS_V9"
    assert model_label("SOME_FUTURE_MODEL_V9") == "SOME_FUTURE_MODEL_V9"


def test_provider_names_are_vendor_names_and_unknown_source_is_not_rewritten():
    assert provider_label("massive") == "Massive"
    assert provider_label("ThetaData") == "ThetaData"
    assert provider_label("saxo") == "Saxo"
    assert provider_label("OPRA") == "OPRA"


def test_app_does_not_ship_mock_strategy_vocabulary_or_false_calibration_ready_state():
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    for invented in ["Gamma Fade", "Skew Roll", "Event Window", "Vol Regime", "Term Structure"]:
        assert invented not in app
    assert 'section_heading("Calibration readiness")' not in app
    assert "DISCOVERY ONLY — NOT READY FOR DECISIONS" not in app  # derived, not hard-coded art
    assert "calibration_evidence_state(" in app
    assert "Backend hypothesis ID" in app
    assert "Backend model ID" in app


def test_provider_roles_are_truthfully_named_without_fake_live_state():
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    assert '"provider": "Massive"' in app
    assert '"provider": "ThetaData"' in app
    assert '"provider": "Saxo"' in app
    assert "Not independently probed on this screen" in app
    assert "Execution disabled" in app


def test_semantic_integrity_contract_is_documented():
    doc = (ROOT / "docs/ui/V1_PRODUCT_INTERFACE.md").read_text(encoding="utf-8")
    assert "UI semantic integrity" in doc
    assert "Aesthetic confidence must never imply scientific confidence" in doc
    assert "Backend hypothesis ID" in doc
    assert "Massive / ThetaData / Saxo" in doc
