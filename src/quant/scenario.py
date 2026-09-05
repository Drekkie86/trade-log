from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable

from src.quant.black_scholes import price
from src.quant.greeks import analytic
from src.quant.types import QuantInputError, VanillaOption


@dataclass(frozen=True)
class ScenarioPoint:
    spot: float
    volatility: float
    time_to_expiry: float
    price: float
    pnl_vs_reference: float
    delta: float | None
    gamma: float | None
    vega: float | None
    theta: float | None

    def as_dict(self) -> dict:
        return asdict(self)


def vanilla_grid(
    reference: VanillaOption,
    *,
    spots: Iterable[float],
    volatilities: Iterable[float],
    times_to_expiry: Iterable[float],
) -> list[ScenarioPoint]:
    reference.validate()
    reference_price = price(reference)
    results: list[ScenarioPoint] = []
    for spot in spots:
        for vol in volatilities:
            for time in times_to_expiry:
                candidate = VanillaOption(
                    spot=float(spot),
                    strike=reference.strike,
                    time_to_expiry=float(time),
                    rate=reference.rate,
                    volatility=float(vol),
                    right=reference.right,
                    dividend_yield=reference.dividend_yield,
                )
                candidate.validate()
                value = price(candidate)
                if candidate.time_to_expiry > 0 and candidate.volatility > 0:
                    g = analytic(candidate)
                    delta, gamma, vega, theta = g.delta, g.gamma, g.vega, g.theta
                else:
                    delta = gamma = vega = theta = None
                results.append(
                    ScenarioPoint(
                        spot=candidate.spot,
                        volatility=candidate.volatility,
                        time_to_expiry=candidate.time_to_expiry,
                        price=value,
                        pnl_vs_reference=value - reference_price,
                        delta=delta,
                        gamma=gamma,
                        vega=vega,
                        theta=theta,
                    )
                )
    if not results:
        raise QuantInputError("scenario grid cannot be empty")
    return results
