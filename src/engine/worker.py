"""One engine step, run by the daemon after every collection iteration.

1. refresh daily close history (chunked, bounded number of provider calls)
2. refresh the implied-vol history behind the risk premium (bounded)
3. estimate each underlying's risk premium (lambda); names without a year of
   matched history cannot pass
4. MAIN lane: score the newest snapshot of every underlying (7-45 DTE), skipping
   names that already have an unexpired pick
5. ZERO_DTE lane: fetch live 0-1 DTE chains for the 0DTE symbols and score
6. freeze the session's picks at the decision scan
7. settle picks and real trades whose expiry has passed
8. prune old stored candidates

Each stage is isolated: a failure is recorded and the next stage still runs.
Nothing here can fail the collection iteration that called it.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta

from src.engine import ENGINE_VERSION
from src.engine.chains import NY, fetch_live_chain, load_main_chains
from src.engine.history import refresh_closes
from src.engine.ledger import (
    open_pick_underlyings, prune_candidates, record_failed_scan, record_scan, settle_due_picks,
    settle_due_trades,
)
from src.engine.pipeline import LANE_MAIN, LANE_ZERO_DTE, main_config, run_scan, zero_dte_config
from src.engine.premium import refresh_iv_history, risk_premium_for

log = logging.getLogger("christiania.engine")

ZERO_DTE_WINDOW = (time(9, 45), time(15, 45))


def zero_dte_symbols() -> list[str]:
    raw = os.environ.get("CHRISTIANIA_ZERO_DTE_SYMBOLS", "SPY,QQQ")
    return [s.strip().upper() for s in raw.split(",") if s.strip()]


def zero_dte_enabled() -> bool:
    return os.environ.get("CHRISTIANIA_ZERO_DTE_ENABLED", "1") != "0"


@dataclass
class EngineStepSummary:
    main_scan_id: int | None = None
    main_passed: int = 0
    zero_dte_scan_id: int | None = None
    zero_dte_passed: int = 0
    settled: int = 0
    trades_settled: int = 0
    closes: dict = field(default_factory=dict)
    iv_history: dict = field(default_factory=dict)
    premiums_ready: int = 0
    pruned: int = 0
    errors: list[str] = field(default_factory=list)


def _zero_dte_open(now: datetime, calendar=None) -> bool:
    from src.operations.market_calendar import get_xnys_calendar

    cal = calendar or get_xnys_calendar()
    local = now.astimezone(NY)
    if not cal.is_session(local.date().isoformat()):
        return False
    close_at = cal.session_close(local.date().isoformat()).to_pydatetime().astimezone(NY)
    end = min(ZERO_DTE_WINDOW[1], (close_at - timedelta(minutes=15)).time())
    return ZERO_DTE_WINDOW[0] <= local.time() <= end


def run_engine_step(*, theta_client, db_path=None, now: datetime | None = None,
                    calendar=None) -> EngineStepSummary:
    from src.database.repository import get_connection

    now = (now or datetime.now(UTC)).astimezone(UTC)
    summary = EngineStepSummary()
    conn = get_connection(db_path)
    try:
        today = now.astimezone(NY).date()
        main_cfg = main_config()
        try:
            chains = load_main_chains(conn, asof=now, max_age=main_cfg.max_quote_age,
                                      min_dte=main_cfg.min_dte, max_dte=main_cfg.max_dte)
        except Exception as exc:
            chains = []
            summary.errors.append(f"main chains: {type(exc).__name__}: {exc}")

        zsyms = zero_dte_symbols() if zero_dte_enabled() else []
        symbols = {c.underlying for c in chains} | set(zsyms)
        try:
            summary.closes = refresh_closes(conn, theta_client, symbols, now=now, calendar=calendar)
        except Exception as exc:
            summary.errors.append(f"closes: {type(exc).__name__}: {exc}")
        try:
            summary.iv_history = refresh_iv_history(conn, theta_client, symbols, now=now,
                                                    calendar=calendar)
        except Exception as exc:
            summary.errors.append(f"iv history: {type(exc).__name__}: {exc}")
        premiums = {}
        for s in sorted(symbols):
            try:
                premiums[s] = risk_premium_for(conn, s, before=today)
            except Exception as exc:
                premiums[s] = None
                summary.errors.append(f"premium {s}: {type(exc).__name__}: {exc}")
        summary.premiums_ready = sum(1 for p in premiums.values() if p is not None)

        if chains:
            try:
                open_names = open_pick_underlyings(conn, LANE_MAIN, today=today)
                result = run_scan(chains, premiums, main_cfg, asof=now, calendar=calendar,
                                  open_underlyings=open_names)
                summary.main_scan_id = record_scan(conn, result, completed_at=datetime.now(UTC))
                summary.main_passed = len(result.passed)
            except Exception as exc:
                log.exception("MAIN engine scan failed")
                summary.errors.append(f"main scan: {type(exc).__name__}: {exc}")
                record_failed_scan(conn, lane=LANE_MAIN, asof=now, config=main_cfg.as_dict(),
                                   error=exc, engine_version=ENGINE_VERSION)

        if zsyms and _zero_dte_open(now, calendar):
            zcfg = zero_dte_config()
            try:
                zchains = [
                    fetch_live_chain(theta_client, s, asof=now,
                                     min_dte=zcfg.min_dte, max_dte=zcfg.max_dte)
                    for s in zsyms
                ]
                zopen = open_pick_underlyings(conn, LANE_ZERO_DTE, today=today)
                zresult = run_scan(zchains, premiums, zcfg, asof=now, calendar=calendar,
                                   open_underlyings=zopen)
                summary.zero_dte_scan_id = record_scan(conn, zresult, completed_at=datetime.now(UTC))
                summary.zero_dte_passed = len(zresult.passed)
            except Exception as exc:
                log.exception("ZERO_DTE engine scan failed")
                summary.errors.append(f"0dte scan: {type(exc).__name__}: {exc}")
                record_failed_scan(conn, lane=LANE_ZERO_DTE, asof=now, config=zcfg.as_dict(),
                                   error=exc, engine_version=ENGINE_VERSION)

        try:
            summary.settled = settle_due_picks(conn, now=now)
            summary.trades_settled = settle_due_trades(conn, now=now)
        except Exception as exc:
            summary.errors.append(f"settlement: {type(exc).__name__}: {exc}")
        try:
            summary.pruned = prune_candidates(conn, now=now)
        except Exception as exc:
            summary.errors.append(f"retention: {type(exc).__name__}: {exc}")
    finally:
        conn.close()
    return summary
