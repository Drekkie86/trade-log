"""One engine step, run by the daemon after every research iteration.

1. refresh daily close history (bounded number of provider calls per step)
2. MAIN lane: score the newest snapshot of every underlying (7-45 DTE)
3. ZERO_DTE lane: fetch live 0-1 DTE chains for the 0DTE symbols and score
4. freeze the top picks of each lane
5. settle picks whose expiry has passed

Each stage is isolated: a failure is recorded and the next stage still runs.
Nothing here can fail the research iteration that called it.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta

from src.engine import ENGINE_VERSION
from src.engine.chains import NY, fetch_live_chain, load_main_chains
from src.engine.history import load_closes, refresh_closes
from src.engine.ledger import record_failed_scan, record_scan, settle_due_picks
from src.engine.pipeline import main_config, run_scan, zero_dte_config

log = logging.getLogger("christiania.engine")

ZERO_DTE_WINDOW = (time(9, 45), time(15, 45))


def zero_dte_symbols() -> list[str]:
    raw = os.environ.get("CHRISTIANIA_ZERO_DTE_SYMBOLS", "SPY,QQQ")
    return [s.strip().upper() for s in raw.split(",") if s.strip()]


@dataclass
class EngineStepSummary:
    main_scan_id: int | None = None
    main_passed: int = 0
    zero_dte_scan_id: int | None = None
    zero_dte_passed: int = 0
    settled: int = 0
    closes: dict = field(default_factory=dict)
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

        symbols = {c.underlying for c in chains} | set(zero_dte_symbols())
        try:
            summary.closes = refresh_closes(conn, theta_client, symbols, now=now,
                                            calendar=calendar)
        except Exception as exc:
            summary.errors.append(f"closes: {type(exc).__name__}: {exc}")

        if chains:
            try:
                closes = {c.underlying: load_closes(conn, c.underlying, before=today)
                          for c in chains}
                result = run_scan(chains, closes, main_cfg, asof=now, calendar=calendar)
                summary.main_scan_id = record_scan(conn, result, completed_at=datetime.now(UTC))
                summary.main_passed = len(result.passed)
            except Exception as exc:
                log.exception("MAIN engine scan failed")
                summary.errors.append(f"main scan: {type(exc).__name__}: {exc}")
                record_failed_scan(conn, lane="MAIN", asof=now, config=main_cfg.as_dict(),
                                   error=exc, engine_version=ENGINE_VERSION)

        if _zero_dte_open(now, calendar):
            zcfg = zero_dte_config()
            try:
                zchains = [
                    fetch_live_chain(theta_client, s, asof=now,
                                     min_dte=zcfg.min_dte, max_dte=zcfg.max_dte)
                    for s in zero_dte_symbols()
                ]
                zcloses = {s: load_closes(conn, s, before=today) for s in zero_dte_symbols()}
                zresult = run_scan(zchains, zcloses, zcfg, asof=now, calendar=calendar)
                summary.zero_dte_scan_id = record_scan(conn, zresult, completed_at=datetime.now(UTC))
                summary.zero_dte_passed = len(zresult.passed)
            except Exception as exc:
                log.exception("ZERO_DTE engine scan failed")
                summary.errors.append(f"0dte scan: {type(exc).__name__}: {exc}")
                record_failed_scan(conn, lane="ZERO_DTE", asof=now, config=zcfg.as_dict(),
                                   error=exc, engine_version=ENGINE_VERSION)

        try:
            summary.settled = settle_due_picks(conn, now=now)
        except Exception as exc:
            summary.errors.append(f"settlement: {type(exc).__name__}: {exc}")
    finally:
        conn.close()
    return summary
