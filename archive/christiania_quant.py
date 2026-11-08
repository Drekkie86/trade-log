from __future__ import annotations

import argparse
import json

from src.quant.bench import run_vanilla_bench
from src.quant.registry import catalog
from src.quant.risk import OptionLeg, evaluate_lognormal
from src.quant.scenario import vanilla_grid
from src.quant.types import VanillaOption


def _option_from_args(args: argparse.Namespace) -> VanillaOption:
    return VanillaOption(
        spot=args.spot,
        strike=args.strike,
        time_to_expiry=args.time,
        rate=args.rate,
        volatility=args.vol,
        right=args.right,
        dividend_yield=args.dividend,
    )


def _print(payload) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Christiania V1 quantitative research bench"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("registry", help="Show the research-only quant model catalog")

    bench = sub.add_parser("bench", help="Compare vanilla-option pricing models")
    for p in (bench,):
        p.add_argument("--spot", type=float, required=True)
        p.add_argument("--strike", type=float, required=True)
        p.add_argument("--time", type=float, required=True, help="Years to expiry")
        p.add_argument("--rate", type=float, required=True)
        p.add_argument("--vol", type=float, required=True)
        p.add_argument("--right", choices=("CALL", "PUT"), default="CALL")
        p.add_argument("--dividend", type=float, default=0.0)
    bench.add_argument("--market-price", type=float)
    bench.add_argument("--tree-steps", type=int, default=500)
    bench.add_argument("--mc-paths", type=int, default=50_000)
    bench.add_argument("--seed", type=int, default=1729)

    scenario = sub.add_parser("scenario", help="Generate a BSM spot/vol/time scenario grid")
    scenario.add_argument("--spot", type=float, required=True)
    scenario.add_argument("--strike", type=float, required=True)
    scenario.add_argument("--time", type=float, required=True)
    scenario.add_argument("--rate", type=float, required=True)
    scenario.add_argument("--vol", type=float, required=True)
    scenario.add_argument("--right", choices=("CALL", "PUT"), default="CALL")
    scenario.add_argument("--dividend", type=float, default=0.0)
    scenario.add_argument("--spot-multipliers", default="0.9,1.0,1.1")
    scenario.add_argument("--vol-multipliers", default="0.8,1.0,1.2")
    scenario.add_argument("--time-multipliers", default="0.5,1.0")

    structure = sub.add_parser("structure", help="Evaluate a defined-risk research structure")
    structure.add_argument("--spot", type=float, required=True)
    structure.add_argument("--time", type=float, required=True)
    structure.add_argument("--rate", type=float, required=True)
    structure.add_argument("--vol", type=float, required=True)
    structure.add_argument("--dividend", type=float, default=0.0)
    structure.add_argument("--costs", type=float, default=0.0)
    structure.add_argument("--slippage", type=float, default=0.0)
    structure.add_argument(
        "--leg",
        action="append",
        required=True,
        help="RIGHT,STRIKE,QTY,ENTRY_PREMIUM; e.g. CALL,100,1,4.20",
    )

    args = parser.parse_args()

    if args.command == "registry":
        _print({"models": catalog(), "governance": "RESEARCH_ONLY"})
        return 0

    if args.command == "bench":
        result = run_vanilla_bench(
            _option_from_args(args),
            market_price=args.market_price,
            tree_steps=args.tree_steps,
            mc_paths=args.mc_paths,
            seed=args.seed,
        )
        _print(result.as_dict())
        return 0

    if args.command == "scenario":
        option = _option_from_args(args)
        spot_mult = [float(x) for x in args.spot_multipliers.split(",")]
        vol_mult = [float(x) for x in args.vol_multipliers.split(",")]
        time_mult = [float(x) for x in args.time_multipliers.split(",")]
        points = vanilla_grid(
            option,
            spots=[option.spot * x for x in spot_mult],
            volatilities=[option.volatility * x for x in vol_mult],
            times_to_expiry=[option.time_to_expiry * x for x in time_mult],
        )
        _print({"points": [p.as_dict() for p in points], "governance": "RESEARCH_ONLY"})
        return 0

    legs = []
    for raw in args.leg:
        right, strike, qty, premium = [part.strip() for part in raw.split(",")]
        legs.append(OptionLeg(right, float(strike), int(qty), float(premium)))
    result = evaluate_lognormal(
        legs,
        spot=args.spot,
        time_to_expiry=args.time,
        rate=args.rate,
        volatility=args.vol,
        dividend_yield=args.dividend,
        transaction_costs=args.costs,
        slippage=args.slippage,
    )
    _print(result.as_dict() | {"governance": "RESEARCH_ONLY"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
