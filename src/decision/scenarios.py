from __future__ import annotations

from typing import Any

from src.quant import black_scholes
from src.quant.types import QuantInputError, VanillaOption

SCENARIOS = (
    ("Down 5%, IV +5", -0.05, 0.05, 1),
    ("Down 2%, IV +2", -0.02, 0.02, 1),
    ("Flat, IV -2", 0.00, -0.02, 1),
    ("Up 2%, IV flat", 0.02, 0.00, 1),
    ("Up 5%, IV +5", 0.05, 0.05, 1),
)


def _float(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def run_structure_scenarios(candidate: dict[str, Any], *, current_tte: float | None) -> dict[str, Any]:
    legs = list(candidate.get("structure_legs") or [])
    spot = _float(candidate.get("underlying_price"))
    if not legs or spot is None or current_tte is None:
        return {"state": "UNAVAILABLE", "rows": [], "reason": "Missing persisted legs, spot or time-to-expiry."}

    rows = []
    for name, spot_shock, vol_shock, days_forward in SCENARIOS:
        structure_value = 0.0
        entry_value = 0.0
        multiplier = None
        try:
            for leg in legs:
                strike = _float(leg.get("strike"))
                vol = _float(leg.get("implied_volatility"))
                if vol is None:
                    vol = _float(leg.get("provider_implied_volatility"))
                rate = _float(leg.get("model_rate"))
                div = _float(leg.get("model_dividend_yield"))
                entry = _float(leg.get("entry_price"))
                mult = _float(leg.get("shares_per_contract")) or 100.0
                if None in (strike, vol, rate, div, entry):
                    raise QuantInputError("incomplete scenario inputs")
                if multiplier is None:
                    multiplier = mult
                elif multiplier != mult:
                    raise QuantInputError("inconsistent multipliers")
                sign = 1.0 if str(leg.get("side")).upper() == "BUY" else -1.0
                qty = abs(int(leg.get("quantity") or 1))
                shocked = VanillaOption(
                    spot=spot * (1.0 + spot_shock),
                    strike=strike,
                    time_to_expiry=max(current_tte - days_forward / 365.0, 0.0),
                    rate=rate,
                    volatility=max(vol + vol_shock, 0.0001),
                    right="CALL" if str(leg.get("right")).upper() in {"C", "CALL"} else "PUT",
                    dividend_yield=div,
                )
                structure_value += sign * qty * black_scholes.price(shocked)
                entry_value += sign * qty * entry
            pnl = (structure_value - entry_value) * float(multiplier or 100.0)
            rows.append({"scenario": name, "spot_shock_pct": spot_shock * 100.0, "iv_shock_points": vol_shock * 100.0, "days_forward": days_forward, "model_pnl_per_structure": pnl})
        except (QuantInputError, TypeError, ValueError):
            return {"state": "UNAVAILABLE", "rows": [], "reason": "Scenario inputs are incomplete or inconsistent."}
    return {"state": "RESEARCH_ONLY", "rows": rows, "reason": "Deterministic BSM stress scenarios with no assigned probabilities; not expected value."}
