from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Iterable


CASINO_ENGINE_VERSION = "1.0.0"
CASINO_NAMESPACE = "CASINO_V1"

CASINO_NO_TRADE = "NO_TRADE"
CASINO_SHADOW_CANDIDATE = "CASINO_SHADOW_CANDIDATE"


@dataclass(frozen=True)
class CasinoRiskPolicy:
    bankroll: float
    casino_cap: float
    max_loss_fraction: float

    def validate(self) -> None:
        if not math.isfinite(self.bankroll) or self.bankroll <= 0:
            raise ValueError("bankroll must be finite and positive")
        if not math.isfinite(self.casino_cap) or self.casino_cap <= 0:
            raise ValueError("casino_cap must be finite and positive")
        if not math.isfinite(self.max_loss_fraction) or not 0 < self.max_loss_fraction <= 1:
            raise ValueError("max_loss_fraction must be in (0, 1]")

    @property
    def experiment_loss_budget(self) -> float:
        return float(min(self.casino_cap, self.bankroll * self.max_loss_fraction))


@dataclass(frozen=True)
class ZeroDteDiagnostics:
    implied_volatility_annualized: float
    forecast_realized_volatility_annualized: float
    remaining_year_fraction: float
    jump_variance_remaining: float = 0.0
    call_iv: float | None = None
    put_iv: float | None = None
    gamma_exposure_cash: float | None = None
    theta_decay_cash_per_day: float | None = None
    bid_ask_spread_fraction: float | None = None
    dealer_positioning_value: float | None = None
    dealer_positioning_source: str | None = None

    def validate(self) -> None:
        for name, value in (
            ("implied_volatility_annualized", self.implied_volatility_annualized),
            ("forecast_realized_volatility_annualized", self.forecast_realized_volatility_annualized),
            ("remaining_year_fraction", self.remaining_year_fraction),
            ("jump_variance_remaining", self.jump_variance_remaining),
        ):
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and non-negative")
        if self.remaining_year_fraction > 1:
            raise ValueError("remaining_year_fraction cannot exceed 1")
        for name, value in (
            ("call_iv", self.call_iv),
            ("put_iv", self.put_iv),
            ("bid_ask_spread_fraction", self.bid_ask_spread_fraction),
        ):
            if value is not None and (not math.isfinite(value) or value < 0):
                raise ValueError(f"{name} must be finite and non-negative when supplied")
        for name, value in (
            ("gamma_exposure_cash", self.gamma_exposure_cash),
            ("theta_decay_cash_per_day", self.theta_decay_cash_per_day),
            ("dealer_positioning_value", self.dealer_positioning_value),
        ):
            if value is not None and not math.isfinite(value):
                raise ValueError(f"{name} must be finite when supplied")
        if self.dealer_positioning_value is not None and not self.dealer_positioning_source:
            raise ValueError("dealer positioning requires an explicit measured source")


@dataclass(frozen=True)
class ZeroDteDiagnosticResult:
    version: str
    namespace: str
    implied_remaining_variance: float
    forecast_remaining_variance: float
    variance_gap_remaining: float
    variance_ratio: float | None
    skew_put_minus_call: float | None
    gamma_theta_abs_ratio: float | None
    liquidity_state: str
    dealer_positioning_state: str
    evidence_label: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def evaluate_0dte_diagnostics(inputs: ZeroDteDiagnostics) -> ZeroDteDiagnosticResult:
    inputs.validate()
    implied = inputs.implied_volatility_annualized**2 * inputs.remaining_year_fraction
    forecast = (
        inputs.forecast_realized_volatility_annualized**2 * inputs.remaining_year_fraction
        + inputs.jump_variance_remaining
    )
    gap = implied - forecast
    ratio = None if forecast <= 0 else float(implied / forecast)
    skew = (
        None
        if inputs.call_iv is None or inputs.put_iv is None
        else float(inputs.put_iv - inputs.call_iv)
    )
    gamma_theta = None
    if (
        inputs.gamma_exposure_cash is not None
        and inputs.theta_decay_cash_per_day is not None
        and abs(inputs.theta_decay_cash_per_day) > 0
    ):
        gamma_theta = float(
            abs(inputs.gamma_exposure_cash) / abs(inputs.theta_decay_cash_per_day)
        )

    if inputs.bid_ask_spread_fraction is None:
        liquidity = "LIQUIDITY_UNKNOWN"
    elif inputs.bid_ask_spread_fraction <= 0.05:
        liquidity = "LIQUIDITY_ACCEPTABLE_FOR_RESEARCH"
    elif inputs.bid_ask_spread_fraction <= 0.15:
        liquidity = "LIQUIDITY_POOR"
    else:
        liquidity = "LIQUIDITY_REJECT"

    dealer_state = (
        "MEASURED_INPUT_AVAILABLE"
        if inputs.dealer_positioning_value is not None
        else "NOT_MEASURED_DO_NOT_INFER"
    )

    return ZeroDteDiagnosticResult(
        version=CASINO_ENGINE_VERSION,
        namespace=CASINO_NAMESPACE,
        implied_remaining_variance=float(implied),
        forecast_remaining_variance=float(forecast),
        variance_gap_remaining=float(gap),
        variance_ratio=ratio,
        skew_put_minus_call=skew,
        gamma_theta_abs_ratio=gamma_theta,
        liquidity_state=liquidity,
        dealer_positioning_state=dealer_state,
        evidence_label="CASINO_RESEARCH_DIAGNOSTIC_NOT_EDGE_PROOF",
    )


@dataclass(frozen=True)
class ScenarioOutcome:
    probability: float
    pnl_before_costs: float

    def validate(self) -> None:
        if not math.isfinite(self.probability) or not 0 <= self.probability <= 1:
            raise ValueError("scenario probability must be in [0, 1]")
        if not math.isfinite(self.pnl_before_costs):
            raise ValueError("scenario pnl must be finite")


@dataclass(frozen=True)
class CasinoExperimentResult:
    version: str
    namespace: str
    state: str
    risk_budget: float
    max_loss: float | None
    expected_pnl_net: float
    probability_of_profit_net: float
    loss_cvar95: float
    expected_pnl_to_max_loss: float | None
    reasons: tuple[str, ...]
    decision_authority: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def evaluate_casino_experiment(
    outcomes: Iterable[ScenarioOutcome],
    *,
    risk_policy: CasinoRiskPolicy,
    defined_risk: bool,
    max_loss: float | None,
    transaction_costs: float,
    slippage: float,
    liquidity_state: str,
) -> CasinoExperimentResult:
    risk_policy.validate()
    rows = list(outcomes)
    if not rows:
        raise ValueError("at least one scenario outcome is required")
    for row in rows:
        row.validate()
    probability_sum = sum(row.probability for row in rows)
    if not math.isclose(probability_sum, 1.0, rel_tol=1e-9, abs_tol=1e-9):
        raise ValueError("scenario probabilities must sum to 1")
    for name, value in (("transaction_costs", transaction_costs), ("slippage", slippage)):
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"{name} must be finite and non-negative")
    if max_loss is not None and (not math.isfinite(max_loss) or max_loss < 0):
        raise ValueError("max_loss must be finite and non-negative when supplied")

    total_costs = float(transaction_costs + slippage)
    net_pnls = [row.pnl_before_costs - total_costs for row in rows]
    expected = float(sum(row.probability * pnl for row, pnl in zip(rows, net_pnls)))
    p_profit = float(sum(row.probability for row, pnl in zip(rows, net_pnls) if pnl > 0))

    weighted_losses = sorted(
        ((max(0.0, -pnl), row.probability) for row, pnl in zip(rows, net_pnls)),
        key=lambda item: item[0],
        reverse=True,
    )
    tail_mass = 0.05
    remaining = tail_mass
    tail_loss_sum = 0.0
    for loss, probability in weighted_losses:
        take = min(remaining, probability)
        tail_loss_sum += loss * take
        remaining -= take
        if remaining <= 1e-12:
            break
    cvar95 = float(tail_loss_sum / tail_mass) if tail_mass > 0 else 0.0

    budget = risk_policy.experiment_loss_budget
    reasons: list[str] = []
    if not defined_risk or max_loss is None:
        reasons.append("UNBOUNDED_OR_UNKNOWN_MAX_LOSS")
    elif max_loss > budget:
        reasons.append("EXCEEDS_CASINO_EXPERIMENT_LOSS_BUDGET")
    if liquidity_state in {"LIQUIDITY_UNKNOWN", "LIQUIDITY_POOR", "LIQUIDITY_REJECT"}:
        reasons.append(liquidity_state)
    if expected <= 0:
        reasons.append("NON_POSITIVE_SCENARIO_EV_AFTER_COSTS")

    state = CASINO_NO_TRADE if reasons else CASINO_SHADOW_CANDIDATE
    ratio = None
    if max_loss is not None and max_loss > 0:
        ratio = float(expected / max_loss)

    return CasinoExperimentResult(
        version=CASINO_ENGINE_VERSION,
        namespace=CASINO_NAMESPACE,
        state=state,
        risk_budget=budget,
        max_loss=max_loss,
        expected_pnl_net=expected,
        probability_of_profit_net=p_profit,
        loss_cvar95=cvar95,
        expected_pnl_to_max_loss=ratio,
        reasons=tuple(reasons),
        decision_authority="CASINO_RESEARCH_SHADOW_ONLY_NO_EXECUTION",
    )
