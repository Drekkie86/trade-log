from __future__ import annotations

from src.quant.types import QuantInputError


def implied_vs_realized(
    implied_volatility: float,
    realized_volatility: float,
) -> dict[str, float]:
    if implied_volatility < 0 or realized_volatility < 0:
        raise QuantInputError("volatilities cannot be negative")
    implied_var = implied_volatility**2
    realized_var = realized_volatility**2
    spread = implied_var - realized_var
    ratio = float("inf") if realized_var == 0 and implied_var > 0 else (
        1.0 if realized_var == 0 else implied_var / realized_var
    )
    return {
        "implied_volatility": implied_volatility,
        "realized_volatility": realized_volatility,
        "implied_variance": implied_var,
        "realized_variance": realized_var,
        "variance_spread": spread,
        "variance_ratio": ratio,
    }
