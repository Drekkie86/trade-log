"""Backtest the trade engine on ThetaData end-of-day option chains.

Run on a machine with the Theta Terminal running (your PC or the server):

    python run_engine_backtest.py --start 2024-07-15 --symbols SPY,QQQ,IWM,AAPL,MSFT,NVDA \
        --cache data/backtest_cache --out data/backtest

The 400 calendar days before --start are fetched as implied-vol history (the
risk premium needs a year of matched sessions before a name can be scored);
with the cache from the earlier runs that warm-up costs no requests. Defaults:
the LIQUID_US_RESEARCH_V1 universe, start 2024-07-15, end = last completed
session, out-of-sample from 2025-01-01, cache and output under ./data.
Payloads are cached, so a rerun re-scores without refetching. Copy summary.json
to the path in CHRISTIANIA_BACKTEST_SUMMARY for the Track record page to show it.
"""
from __future__ import annotations

import argparse
import os
import shutil
from datetime import UTC, date, datetime
from pathlib import Path

from src.engine.backtest import BacktestSettings, run_backtest, write_report
from src.engine.history import last_completed_session
from src.providers.thetadata import ThetaDataClient
from src.research.universe_profiles import LIQUID_US_RESEARCH_V1


def _money(x) -> str:
    return "n/a" if x is None else f"${x:,.0f}"


def _pct(x) -> str:
    return "n/a" if x is None else f"{100 * x:.1f}%"


def _print_block(title: str, b: dict) -> None:
    print(f"{title}: {b['settled']} settled over {b['expiry_days']} expiry days; "
          f"P&L {_money(b['total_pnl_usd'])} on {_money(b['total_risk_usd'])} at risk "
          f"(return on risk {_pct(b['return_on_risk'])}); average {b['avg_pnl_usd']} "
          f"(bootstrap 95% {b['avg_pnl_ci95_usd']}); hit {_pct(b['hit_rate'])} vs "
          f"{_pct(b['predicted_hit_rate'])} predicted; full loss {_pct(b['max_loss_rate'])} vs "
          f"{_pct(b['predicted_max_loss_rate'])}; max drawdown {_money(b['max_drawdown_usd'])}; "
          f"worst month {b['worst_month']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--symbols", default=",".join(LIQUID_US_RESEARCH_V1))
    parser.add_argument("--start", default="2024-07-15")
    parser.add_argument("--end", default=None)
    parser.add_argument("--oos-start", default="2025-01-01",
                        help="first session of the out-of-sample window (pre-registered criteria apply)")
    parser.add_argument("--cache", default="data/backtest_cache")
    parser.add_argument("--stock-pace", type=float, default=2.1,
                        help="seconds between stock EOD requests (FREE tier allows 30/min)")
    parser.add_argument("--option-pace", type=float, default=0.0,
                        help="seconds between option chain requests")
    parser.add_argument("--out", default="data/backtest")
    parser.add_argument("--theta-base-url", default=os.environ.get("CHRISTIANIA_THETA_BASE_URL",
                                                                    "http://127.0.0.1:25503/v3"))
    parser.add_argument("--summary-to", default=os.environ.get("CHRISTIANIA_BACKTEST_SUMMARY"))
    args = parser.parse_args()

    end = date.fromisoformat(args.end) if args.end else last_completed_session(datetime.now(UTC))
    settings = BacktestSettings(
        symbols=tuple(s.strip().upper() for s in args.symbols.split(",") if s.strip()),
        start=date.fromisoformat(args.start), end=end, cache_dir=Path(args.cache),
        stock_pace_seconds=args.stock_pace, option_pace_seconds=args.option_pace,
        oos_start=date.fromisoformat(args.oos_start) if args.oos_start else None,
    )
    client = ThetaDataClient(base_url=args.theta_base_url, timeout_seconds=120.0)
    report = run_backtest(client, settings, progress=print)
    paths = write_report(report, Path(args.out))
    s = report.summary
    print()
    print(f"Engine {s['engine_version']}; sessions {s['period']['sessions']} "
          f"({s['period']['start']} to {s['period']['end']}), picks {s['picks']}, settled {s['settled']}")
    _print_block("All picks", s)
    _print_block(f"Calibration (before {args.oos_start})", s["calibration"])
    _print_block(f"Out of sample (from {args.oos_start})", s["out_of_sample"])
    _print_block("Single slot, out of sample", s["single_slot"]["out_of_sample"])
    crit = s["criteria"]
    print(f"Pre-registered verdict: {crit['verdict']}")
    for name, check in crit["checks"].items():
        print(f"  {'PASS' if check['pass'] else 'FAIL'} {name}: {check}")
    cov = s.get("coverage", {})
    if cov.get("aborted_reason"):
        print(f"ABORTED: {cov['aborted_reason']}")
    print(f"Written: {', '.join(str(p) for p in paths.values())}")
    if args.summary_to:
        Path(args.summary_to).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(paths["summary"], args.summary_to)
        print(f"Summary copied to {args.summary_to}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
