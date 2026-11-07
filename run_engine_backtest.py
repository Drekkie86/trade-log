"""Backtest the trade engine on ThetaData end-of-day option chains.

Run on a machine with the Theta Terminal running (your PC or the server):

    python run_engine_backtest.py --start 2023-07-03 --end 2026-10-31 \
        --symbols SPY,QQQ,IWM,AAPL,MSFT,NVDA --cache data/backtest_cache --out data/backtest

Defaults: the LIQUID_US_RESEARCH_V1 universe, start 2023-07-03, end = last
completed session, cache and output under ./data. Payloads are cached, so a
rerun (for example with CHRISTIANIA_FORECAST_WEIGHT or the commission changed)
re-scores without refetching. Copy summary.json to the path in
CHRISTIANIA_BACKTEST_SUMMARY for the Track record page to show it.
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--symbols", default=",".join(LIQUID_US_RESEARCH_V1))
    parser.add_argument("--start", default="2023-07-03")
    parser.add_argument("--end", default=None)
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
    )
    client = ThetaDataClient(base_url=args.theta_base_url, timeout_seconds=120.0)
    report = run_backtest(client, settings, progress=print)
    paths = write_report(report, Path(args.out))
    s = report.summary
    print()
    print(f"Sessions {s['period']['sessions']} ({s['period']['start']} to {s['period']['end']}), "
          f"picks {s['picks']}, settled {s['settled']}")
    print(f"Total P&L ${s['total_pnl_usd']:,.0f} on ${s['total_risk_usd']:,.0f} at risk; "
          f"average trade {s['avg_pnl_usd']} (bootstrap 95% {s['avg_pnl_ci95_usd']}); "
          f"hit rate {s['hit_rate']} vs predicted {s['predicted_hit_rate']}")
    print(f"Max drawdown ${s['max_drawdown_usd']:,.0f}; worst day ${s['worst_day_usd']}; "
          f"worst month {s['worst_month']}")
    print(f"Written: {', '.join(str(p) for p in paths.values())}")
    if args.summary_to:
        Path(args.summary_to).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(paths["summary"], args.summary_to)
        print(f"Summary copied to {args.summary_to}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
