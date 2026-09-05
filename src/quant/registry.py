from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class QuantModelRegistration:
    model_id: str
    family: str
    role: str
    decision_enabled: bool
    admission_enabled: bool
    notes: str

    def as_dict(self) -> dict:
        return asdict(self)


MODEL_CATALOG = (
    QuantModelRegistration("BLACK_SCHOLES_MERTON", "closed_form", "FOUNDATION", False, False, "European vanilla benchmark with continuous dividend yield."),
    QuantModelRegistration("BLACK_76", "closed_form", "FOUNDATION", False, False, "Forward/futures option benchmark."),
    QuantModelRegistration("CRR_BINOMIAL", "tree", "DIAGNOSTIC_CHALLENGER", False, False, "European/American cross-check."),
    QuantModelRegistration("CRANK_NICOLSON_BSM", "finite_difference", "DIAGNOSTIC_CHALLENGER", False, False, "European BSM PDE cross-check."),
    QuantModelRegistration("MONTE_CARLO_GBM", "simulation", "DIAGNOSTIC_CHALLENGER", False, False, "Risk-neutral simulation with antithetic/control-variate variance reduction."),
    QuantModelRegistration("HESTON", "stochastic_volatility", "EXPERIMENTAL_CHALLENGER", False, False, "Stochastic volatility with calibration diagnostics."),
    QuantModelRegistration("MERTON_JUMP_DIFFUSION", "jump_diffusion", "EXPERIMENTAL_CHALLENGER", False, False, "Lognormal jump mixture for jump-risk diagnostics."),
    QuantModelRegistration("SVI", "volatility_surface", "EXPERIMENTAL_CHALLENGER", False, False, "Raw SVI total-variance smile fit; sampled diagnostics only."),
    QuantModelRegistration("SABR_HAGAN", "volatility_surface", "EXPERIMENTAL_CHALLENGER", False, False, "Hagan lognormal SABR approximation."),
    QuantModelRegistration("DUPIRE_LOCAL_VOL", "local_volatility", "EXPERIMENTAL_DIAGNOSTIC", False, False, "Finite-difference local-vol extraction; invalid points fail closed."),
    QuantModelRegistration("EWMA", "volatility_forecast", "DIAGNOSTIC_CHALLENGER", False, False, "Exponentially weighted variance forecast."),
    QuantModelRegistration("GARCH_11", "volatility_forecast", "EXPERIMENTAL_CHALLENGER", False, False, "Gaussian GARCH(1,1) baseline forecast."),
)


def catalog() -> list[dict]:
    return [item.as_dict() for item in MODEL_CATALOG]
