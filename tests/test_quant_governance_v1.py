from __future__ import annotations

from pathlib import Path

from src.quant.registry import MODEL_CATALOG, catalog


ROOT = Path(__file__).resolve().parents[1]
QUANT = ROOT / "src" / "quant"


def test_every_quant_model_is_research_only():
    assert MODEL_CATALOG
    for model in MODEL_CATALOG:
        assert model.decision_enabled is False
        assert model.admission_enabled is False
        assert model.role in {
            "FOUNDATION",
            "DIAGNOSTIC_CHALLENGER",
            "EXPERIMENTAL_CHALLENGER",
            "EXPERIMENTAL_DIAGNOSTIC",
        }


def test_quant_catalog_has_advanced_model_families():
    ids = {row["model_id"] for row in catalog()}
    assert {
        "BLACK_SCHOLES_MERTON",
        "CRR_BINOMIAL",
        "MONTE_CARLO_GBM",
        "HESTON",
        "MERTON_JUMP_DIFFUSION",
        "SVI",
        "SABR_HAGAN",
        "DUPIRE_LOCAL_VOL",
        "EWMA",
        "GARCH_11",
    } <= ids


def test_quant_package_contains_no_broker_order_or_admission_imports():
    forbidden = (
        "place_order(",
        "submit_order(",
        "send_order(",
        "execute_order(",
        "src.providers.saxo",
        "shadow_admission",
        "trade_service",
    )
    for path in QUANT.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in text, f"{token!r} found in {path.name}"


def test_quant_package_does_not_import_database_repository():
    for path in QUANT.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "src.database.repository" not in text


def test_quant_docs_make_model_disagreement_non_signal_explicit():
    doc = (ROOT / "docs" / "quant" / "V1_MODEL_DISAGREEMENT.md").read_text(encoding="utf-8")
    assert "not trade signals" in doc
    assert "does not grant it decision authority" in doc


def test_quant_validation_standard_requires_redundant_methods():
    doc = (ROOT / "docs" / "quant" / "V1_QUANT_VALIDATION_STANDARD.md").read_text(encoding="utf-8")
    for phrase in (
        "put-call parity",
        "tree convergence",
        "analytic-vs-numerical Greeks",
        "Heston zero-vol-of-vol limit",
        "Merton zero-jump limit",
    ):
        assert phrase in doc


def test_scipy_dependency_is_declared_for_runtime_and_ci():
    for name in ("requirements.txt", "requirements-ci.txt"):
        req = (ROOT / name).read_text(encoding="utf-8")
        assert "scipy>=1.14,<2" in req


def test_quant_library_is_documented_as_side_effect_free():
    architecture = (ROOT / "docs/V1_ARCHITECTURE.md").read_text(encoding="utf-8")
    assert "`src/quant` is a side-effect-free research library" in architecture
