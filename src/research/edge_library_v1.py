from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Any

from src.quant.types import QuantInputError


EDGE_LIBRARY_VERSION = "1.0.0"
TRADING_DAYS_PER_YEAR = 252.0


@dataclass(frozen=True)
class EdgeDefinition:
    edge_key: str
    name: str
    status: str
    capital_compatibility: str
    defined_risk_required: bool
    activation_state: str
    evidence_authority: str
    prerequisite: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class VarianceGapDiagnostic:
    version: str
    implied_volatility_annualized: float
    forecast_daily_variance: float
    forecast_volatility_annualized: float
    implied_variance_annualized: float
    forecast_variance_annualized: float
    variance_gap_annualized: float
    variance_ratio: float
    normalized_gap: float | None
    diagnostic_state: str
    decision_authority: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


EDGE_LIBRARY: tuple[EdgeDefinition, ...] = (
    EdgeDefinition(
        edge_key="VARIANCE_RISK_PREMIUM",
        name="Variance risk premium",
        status="RESEARCHABLE_DEFINED_RISK_ONLY",
        capital_compatibility="CONDITIONAL",
        defined_risk_required=True,
        activation_state="NOT_ACTIVATED",
        evidence_authority="HYPOTHESIS_ONLY",
        prerequisite="Forecast-RV evidence plus bounded-loss structure and prospective validation.",
    ),
    EdgeDefinition(
        edge_key="IV_FORECAST_RV_GAP",
        name="Implied versus forecast realized-volatility gap",
        status="CORE_CANDIDATE_REQUIRES_FORECAST_MODEL",
        capital_compatibility="COMPATIBLE_IF_BOUNDED",
        defined_risk_required=True,
        activation_state="NOT_ACTIVATED",
        evidence_authority="DIAGNOSTIC_ONLY",
        prerequisite="Prospectively scored realized-variance forecasts and matched option-horizon IV.",
    ),
    EdgeDefinition(
        edge_key="DEMAND_PRESSURE",
        name="Demand pressure / intermediary constraints",
        status="CANDIDATE_REQUIRES_DATA_BASELINES",
        capital_compatibility="UNKNOWN",
        defined_risk_required=True,
        activation_state="NOT_ACTIVATED",
        evidence_authority="HYPOTHESIS_ONLY",
        prerequisite="Normalized volume/open-interest and liquidity baselines.",
    ),
    EdgeDefinition(
        edge_key="IDIOSYNCRATIC_VOLATILITY",
        name="Idiosyncratic-volatility effect",
        status="CANDIDATE_REQUIRES_FACTOR_MODEL",
        capital_compatibility="UNKNOWN",
        defined_risk_required=True,
        activation_state="NOT_ACTIVATED",
        evidence_authority="HYPOTHESIS_ONLY",
        prerequisite="Validated factor-model residual-volatility infrastructure.",
    ),
    EdgeDefinition(
        edge_key="OPTION_MOMENTUM",
        name="Option momentum",
        status="SHADOW_ONLY",
        capital_compatibility="UNKNOWN",
        defined_risk_required=True,
        activation_state="NOT_ACTIVATED",
        evidence_authority="HYPOTHESIS_ONLY",
        prerequisite="Independent reproduction after costs, then prospective shadow evidence.",
    ),
    EdgeDefinition(
        edge_key="QUARTERLY_VARIANCE_SEASONALITY",
        name="Quarterly variance seasonality",
        status="SHADOW_ONLY",
        capital_compatibility="UNKNOWN",
        defined_risk_required=True,
        activation_state="NOT_ACTIVATED",
        evidence_authority="HYPOTHESIS_ONLY",
        prerequisite="Independent Christiania reproduction and prospective seasonal observations.",
    ),
    EdgeDefinition(
        edge_key="EARNINGS_EVENT_PREMIUM",
        name="Earnings / event volatility premium",
        status="EVENT_RESEARCH",
        capital_compatibility="CONDITIONAL",
        defined_risk_required=True,
        activation_state="NOT_ACTIVATED",
        evidence_authority="HYPOTHESIS_ONLY",
        prerequisite="Event calendar, jump-variance estimate, matched non-event baseline and bounded loss.",
    ),
    EdgeDefinition(
        edge_key="CORRELATION_DISPERSION",
        name="Correlation / dispersion",
        status="RESEARCH_ONLY_CAPITAL_INCOMPATIBLE",
        capital_compatibility="INCOMPATIBLE_CURRENT_BANKROLL",
        defined_risk_required=True,
        activation_state="NOT_ACTIVATED",
        evidence_authority="RESEARCH_CONTEXT_ONLY",
        prerequisite="Larger capital base and multi-leg execution infrastructure.",
    ),
    EdgeDefinition(
        edge_key="ZERO_DTE",
        name="0DTE intraday volatility / microstructure research",
        status="CASINO_UNVERIFIED_UNTIL_PROVEN",
        capital_compatibility="CASINO_ONLY",
        defined_risk_required=True,
        activation_state="NOT_ACTIVATED",
        evidence_authority="CASINO_RESEARCH_ONLY",
        prerequisite="Separate Casino namespace, intraday evidence, costs, jump/gamma controls and hard loss cap.",
    ),
)


def edge_registry() -> tuple[EdgeDefinition, ...]:
    return EDGE_LIBRARY


def edge_by_key(edge_key: str) -> EdgeDefinition:
    normalized = edge_key.strip().upper()
    for item in EDGE_LIBRARY:
        if item.edge_key == normalized:
            return item
    raise KeyError(edge_key)


def variance_gap_diagnostic(
    *,
    implied_volatility_annualized: float,
    forecast_daily_variance: float,
    forecast_error_std_daily_variance: float | None = None,
) -> VarianceGapDiagnostic:
    if not math.isfinite(implied_volatility_annualized) or implied_volatility_annualized < 0:
        raise QuantInputError("implied_volatility_annualized must be finite and non-negative")
    if not math.isfinite(forecast_daily_variance) or forecast_daily_variance < 0:
        raise QuantInputError("forecast_daily_variance must be finite and non-negative")
    if forecast_error_std_daily_variance is not None:
        if (
            not math.isfinite(forecast_error_std_daily_variance)
            or forecast_error_std_daily_variance <= 0
        ):
            raise QuantInputError("forecast_error_std_daily_variance must be finite and positive")

    implied_variance = implied_volatility_annualized**2
    forecast_variance = forecast_daily_variance * TRADING_DAYS_PER_YEAR
    forecast_volatility = math.sqrt(max(forecast_variance, 0.0))
    gap = implied_variance - forecast_variance
    if forecast_variance == 0:
        ratio = math.inf if implied_variance > 0 else 1.0
    else:
        ratio = implied_variance / forecast_variance

    normalized_gap = None
    if forecast_error_std_daily_variance is not None:
        normalized_gap = gap / (forecast_error_std_daily_variance * TRADING_DAYS_PER_YEAR)

    return VarianceGapDiagnostic(
        version=EDGE_LIBRARY_VERSION,
        implied_volatility_annualized=float(implied_volatility_annualized),
        forecast_daily_variance=float(forecast_daily_variance),
        forecast_volatility_annualized=float(forecast_volatility),
        implied_variance_annualized=float(implied_variance),
        forecast_variance_annualized=float(forecast_variance),
        variance_gap_annualized=float(gap),
        variance_ratio=float(ratio),
        normalized_gap=None if normalized_gap is None else float(normalized_gap),
        diagnostic_state="RESEARCH_DIAGNOSTIC_NOT_EDGE_PROOF",
        decision_authority="NONE_RESEARCH_ONLY",
    )
