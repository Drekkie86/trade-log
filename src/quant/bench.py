from __future__ import annotations

from dataclasses import asdict, dataclass

from src.quant import black_scholes, finite_difference, greeks, heston, implied_vol, merton_jump, monte_carlo, trees
from src.quant.disagreement import summarize
from src.quant.heston import HestonParameters
from src.quant.merton_jump import MertonJumpParameters
from src.quant.types import VanillaOption


@dataclass(frozen=True)
class VanillaBenchResult:
    input: dict
    model_prices: dict[str, float]
    disagreement: dict
    greeks: dict
    implied_volatility: dict | None
    monte_carlo: dict
    heston_parameters: dict
    merton_parameters: dict
    governance: dict

    def as_dict(self) -> dict:
        return asdict(self)


def run_vanilla_bench(
    option: VanillaOption,
    *,
    market_price: float | None = None,
    heston_params: HestonParameters | None = None,
    merton_params: MertonJumpParameters | None = None,
    tree_steps: int = 500,
    mc_paths: int = 50_000,
    seed: int = 1729,
) -> VanillaBenchResult:
    option.validate()
    heston_params = heston_params or HestonParameters(
        kappa=1.5,
        theta=option.volatility**2,
        vol_of_vol=0.35,
        rho=-0.5,
        v0=max(option.volatility**2, 1e-6),
    )
    merton_params = merton_params or MertonJumpParameters(
        jump_intensity=0.15,
        jump_mean=-0.05,
        jump_volatility=0.20,
    )

    mc = monte_carlo.price(option, paths=mc_paths, seed=seed)
    prices = {
        "BLACK_SCHOLES_MERTON": black_scholes.price(option),
        "CRR_BINOMIAL": trees.crr_price(option, steps=tree_steps),
        "CRANK_NICOLSON_BSM": finite_difference.crank_nicolson_price(
            option, spot_steps=240, time_steps=240
        ),
        "MONTE_CARLO_GBM": mc.price,
        "HESTON": heston.price(option, heston_params),
        "MERTON_JUMP_DIFFUSION": merton_jump.price(option, merton_params),
    }
    iv = None
    if market_price is not None:
        iv = implied_vol.solve(market_price, option).as_dict()

    g = greeks.analytic(option) if option.time_to_expiry > 0 and option.volatility > 0 else None
    return VanillaBenchResult(
        input=asdict(option),
        model_prices=prices,
        disagreement=summarize(prices, market_price=market_price).as_dict(),
        greeks={} if g is None else g.as_dict(),
        implied_volatility=iv,
        monte_carlo=mc.as_dict(),
        heston_parameters=heston_params.as_dict() | {"feller_ratio": heston_params.feller_ratio},
        merton_parameters=merton_params.as_dict(),
        governance={
            "state": "RESEARCH_ONLY",
            "decision_enabled": False,
            "admission_enabled": False,
            "warning": "Model disagreement is diagnostic evidence, not a trade signal.",
        },
    )
