from __future__ import annotations

import math

import pytest

from src.quant.types import QuantInputError
from src.research.edge_library_v1 import (
    edge_by_key,
    edge_registry,
    variance_gap_diagnostic,
)
from src.research.edge_risk_runtime_v1 import load_edge_risk_runtime


def test_edge_registry_preserves_scientific_and_capital_boundaries() -> None:
    registry = edge_registry()
    keys = {item.edge_key for item in registry}
    assert "VARIANCE_RISK_PREMIUM" in keys
    assert "IV_FORECAST_RV_GAP" in keys
    assert "CORRELATION_DISPERSION" in keys
    assert "ZERO_DTE" in keys
    assert all(item.activation_state == "NOT_ACTIVATED" for item in registry)
    assert all(item.defined_risk_required for item in registry)

    vrp = edge_by_key("variance_risk_premium")
    assert vrp.status == "RESEARCHABLE_DEFINED_RISK_ONLY"
    assert vrp.evidence_authority == "HYPOTHESIS_ONLY"

    dispersion = edge_by_key("CORRELATION_DISPERSION")
    assert dispersion.capital_compatibility == "INCOMPATIBLE_CURRENT_BANKROLL"

    zero_dte = edge_by_key("ZERO_DTE")
    assert zero_dte.capital_compatibility == "CASINO_ONLY"


def test_variance_gap_uses_variance_units_and_optional_normalization() -> None:
    result = variance_gap_diagnostic(
        implied_volatility_annualized=0.30,
        forecast_daily_variance=0.0002,
        forecast_error_std_daily_variance=0.00005,
    )
    assert result.implied_variance_annualized == pytest.approx(0.09)
    assert result.forecast_variance_annualized == pytest.approx(0.0002 * 252)
    assert result.forecast_volatility_annualized == pytest.approx(math.sqrt(0.0002 * 252))
    assert result.variance_gap_annualized == pytest.approx(0.09 - 0.0002 * 252)
    assert result.normalized_gap == pytest.approx(
        (0.09 - 0.0002 * 252) / (0.00005 * 252)
    )
    assert result.diagnostic_state == "RESEARCH_DIAGNOSTIC_NOT_EDGE_PROOF"
    assert result.decision_authority == "NONE_RESEARCH_ONLY"


def test_variance_gap_zero_forecast_is_explicit_not_silently_clipped() -> None:
    result = variance_gap_diagnostic(
        implied_volatility_annualized=0.20,
        forecast_daily_variance=0.0,
    )
    assert math.isinf(result.variance_ratio)
    assert result.normalized_gap is None


def test_variance_gap_invalid_uncertainty_fails_closed() -> None:
    with pytest.raises(QuantInputError):
        variance_gap_diagnostic(
            implied_volatility_annualized=0.20,
            forecast_daily_variance=0.0001,
            forecast_error_std_daily_variance=0.0,
        )


def test_missing_database_runtime_is_read_only_and_retains_governance(tmp_path) -> None:
    missing = tmp_path / "does-not-exist.db"
    state = load_edge_risk_runtime(missing)
    assert state.state == "DATABASE_UNAVAILABLE"
    assert state.observations == ()
    assert state.decision_authority == "NONE_RESEARCH_ONLY"
    assert state.family_activation_authority == "NONE_PROGRAMME_BUDGET_UNFROZEN"
    assert any(item["edge_key"] == "VARIANCE_RISK_PREMIUM" for item in state.edge_library)
    assert not missing.exists()
