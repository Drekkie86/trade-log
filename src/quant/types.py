from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping


class QuantInputError(ValueError):
    """Raised when a quantitative model receives an invalid domain input."""


@dataclass(frozen=True)
class VanillaOption:
    spot: float
    strike: float
    time_to_expiry: float
    rate: float
    volatility: float
    right: str = "CALL"
    dividend_yield: float = 0.0

    def normalized_right(self) -> str:
        right = self.right.upper()
        if right not in {"CALL", "PUT"}:
            raise QuantInputError("right must be CALL or PUT")
        return right

    def validate(self) -> None:
        self.normalized_right()
        if self.spot <= 0.0:
            raise QuantInputError("spot must be positive")
        if self.strike <= 0.0:
            raise QuantInputError("strike must be positive")
        if self.time_to_expiry < 0.0:
            raise QuantInputError("time_to_expiry cannot be negative")
        if self.volatility < 0.0:
            raise QuantInputError("volatility cannot be negative")


@dataclass(frozen=True)
class Greeks:
    delta: float
    gamma: float
    vega: float
    theta: float
    rho: float
    vanna: float
    vomma: float
    charm: float

    def as_dict(self) -> dict[str, float]:
        return asdict(self)


@dataclass(frozen=True)
class PriceEstimate:
    model: str
    price: float
    diagnostics: Mapping[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "price": self.price,
            "diagnostics": dict(self.diagnostics),
        }


@dataclass(frozen=True)
class CalibrationDiagnostics:
    converged: bool
    rmse: float
    mae: float
    max_abs_error: float
    observations: int
    objective: float | None = None
    message: str | None = None
    boundary_hits: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)
