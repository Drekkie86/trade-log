"""Cost diagnostic: re-price the picks of a finished backtest at different fill assumptions.

Read-only. Uses the picks.csv of a run and the option cache that run used; needs no
Theta Terminal and fetches nothing. The picks are NOT re-selected: the same trades are
re-priced, so the question answered is "was there any signal before costs?".

    python scripts/cost_diagnostic.py --picks data\\backtest_universe\\picks.csv ^
        --cache data\\backtest_cache --out data\\cost_diagnostic

Self-check: at slippage 0.5 and $2.00 per leg the script must reproduce the run's own
pnl_usd for every pick to within a cent; otherwise it stops.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import date
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.engine.eod import quotes_from_eod_rows  # noqa: E402

LEG = re.compile(r"(Buy|Sell)\s+([0-9.]+)([CP])")
OOS_START = "2025-01-01"
SCENARIOS = [  # (label, slippage fraction, commission per leg)
    ("run_as_reported", 0.5, 2.00),
    ("no_commission", 0.5, 0.0),
    ("no_slippage", 0.0, 2.00),
    ("mid_fill_no_commission", 0.0, 0.0),
    ("quarter_slippage_ibkr_like", 0.25, 0.65),
    ("best_case_quarter_slippage_no_comm", 0.25, 0.0),
]


def legs_of(description: str) -> list[tuple[int, float, str]]:
    return [(1 if side == "Buy" else -1, float(strike), right) for side, strike, right in LEG.findall(description)]


def load_quotes(cache: Path, symbol: str, session: str) -> dict:
    path = cache / "option_eod" / symbol / f"{session}.json"
    rows = json.loads(path.read_text(encoding="utf-8"))
    return {(q.expiration, q.right, q.strike): q for q in quotes_from_eod_rows(rows, date.fromisoformat(session))}


def payoff(legs, price: float) -> float:
    total = 0.0
    for side, strike, right in legs:
        intrinsic = max(price - strike, 0.0) if right == "C" else max(strike - price, 0.0)
        total += side * intrinsic
    return total


def price_pick(pick: dict, quotes: dict, slippage: float, commission_per_leg: float) -> float:
    legs = legs_of(pick["description"])
    entry = 0.0
    for side, strike, right in legs:
        q = quotes[(pick["expiration"], right, strike)]
        half = 0.5 * (q.ask - q.bid)
        fill = q.mid + slippage * half if side > 0 else q.mid - slippage * half
        entry += -side * fill
    return (payoff(legs, float(pick["settlement_price"])) + entry) * 100.0 - commission_per_leg * len(legs)


def stats(values: list[float], risk: list[float]) -> dict:
    a = np.array(values)
    return {"n": len(a), "total": round(float(a.sum()), 2), "avg": round(float(a.mean()), 2) if len(a) else None,
            "hit": round(float((a > 0).mean()), 4) if len(a) else None,
            "return_on_risk": round(float(a.sum()) / sum(risk), 4) if risk else None}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--picks", required=True)
    ap.add_argument("--cache", default="data/backtest_cache")
    ap.add_argument("--out", default="data/cost_diagnostic")
    args = ap.parse_args()
    cache = Path(args.cache)

    with open(args.picks, newline="", encoding="utf-8") as f:
        picks = [p for p in csv.DictReader(f) if p["pnl_usd"] not in ("", None)]
    print(f"{len(picks)} settled picks")

    rows, missing = [], 0
    for p in picks:
        try:
            quotes = load_quotes(cache, p["underlying"], p["session"])
            rec = {"pick": p, "pnl": {label: price_pick(p, quotes, s, c) for label, s, c in SCENARIOS},}
            legs = legs_of(p["description"])
            rec["half_spread_usd"] = 100.0 * sum(0.5 * (quotes[(p["expiration"], r, k)].ask
                                                        - quotes[(p["expiration"], r, k)].bid)
                                                  for _, k, r in legs)
        except (OSError, KeyError, ValueError, TypeError):
            missing += 1
            continue
        rows.append(rec)
    if missing:
        print(f"WARNING: {missing} picks could not be re-priced (cache entry or leg missing)")
    if not rows:
        print("nothing re-priced; check --cache")
        return 1

    worst = max(abs(r["pnl"]["run_as_reported"] - float(r["pick"]["pnl_usd"])) for r in rows)
    print(f"self-check: largest difference to the run's own pnl_usd = ${worst:.4f}")
    if worst > 0.02:
        print("STOP: the re-pricing does not reproduce the run; do not interpret the numbers below.")
        return 2

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    result = {"picks_repriced": len(rows), "missing": missing, "self_check_max_diff_usd": round(worst, 4),
              "avg_half_spread_paid_usd": round(float(np.mean([r["half_spread_usd"] for r in rows])), 2),
              "avg_commission_usd_as_run": round(float(np.mean([2.0 * len(legs_of(r["pick"]["description"]))
                                                               for r in rows])), 2),
              "scenarios": {}}
    for label, _, _ in SCENARIOS:
        block = {}
        for name, sel in (("all", lambda r: True), ("out_of_sample", lambda r: r["pick"]["session"] >= OOS_START)):
            sub = [r for r in rows if sel(r)]
            block[name] = stats([r["pnl"][label] for r in sub], [float(r["pick"]["max_loss_usd"]) for r in sub])
        result["scenarios"][label] = block
    # per family at mid fill with no commission: is there a signal in any structure?
    fam = {}
    for family in sorted({r["pick"]["family"] for r in rows}):
        sub = [r for r in rows if r["pick"]["family"] == family]
        fam[family] = stats([r["pnl"]["mid_fill_no_commission"] for r in sub],
                            [float(r["pick"]["max_loss_usd"]) for r in sub])
    result["by_family_mid_fill_no_commission"] = fam
    (out / "cost_diagnostic.json").write_text(json.dumps(result, indent=2), encoding="utf-8")

    print(json.dumps({k: v for k, v in result.items() if k != "scenarios"}, indent=2))
    for label, block in result["scenarios"].items():
        a, o = block["all"], block["out_of_sample"]
        print(f"{label:38s} all {a['total']:>10,.0f} (avg {a['avg']})  oos {o['total']:>10,.0f} (avg {o['avg']})")
    print(f"wrote {out / 'cost_diagnostic.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
