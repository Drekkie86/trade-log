"""Historical backtest of the engine on ThetaData end-of-day option chains.

For every session in the range: build each symbol's chain from the EOD report
(last NBBO at report time, so the "decision" is taken at the close), run the
same ``run_scan`` the daemon runs, freeze the best structure per underlying
(at most ``top_n``), and settle each pick at expiry on the stock EOD close.
Raw provider payloads are cached on disk so a run can be resumed and re-scored
without refetching.

The result is the one piece of evidence the live track record cannot provide:
how the engine's picks behaved through past volatility shocks.
"""
from __future__ import annotations

import csv
import json
import math
import time as clock
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

import numpy as np

from src.engine import ENGINE_VERSION
from src.engine.chains import NY, Quote, build_chain
from src.engine.history import DailyClose, fetch_eod_closes
from src.engine.ledger import cluster_bootstrap_ci, drawdown, pick_pnl_at
from src.engine.pipeline import EngineConfig, main_config, run_scan

DECISION_CLOCK = time(15, 59, 30)


@dataclass(frozen=True)
class BacktestSettings:
    symbols: tuple[str, ...]
    start: date
    end: date
    cache_dir: Path
    config: EngineConfig = field(default_factory=main_config)
    max_dte: int = 45
    stock_pace_seconds: float = 2.1      # FREE stock tier: 30 requests/minute
    option_pace_seconds: float = 0.0

    @property
    def top_n(self) -> int:
        return self.config.top_n


# ------------------------------------------------------------------ provider
def _flatten(payload: Any) -> list[dict]:
    rows = payload.get("response") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise ValueError("ThetaData option EOD payload is not a list")
    flat: list[dict] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        contract, data = item.get("contract"), item.get("data")
        if isinstance(contract, dict) and isinstance(data, list):
            for obs in data:
                if isinstance(obs, dict):
                    flat.append({**contract, **obs})
        else:
            flat.append(dict(item))
    return flat


def _right(value: Any) -> str | None:
    text = str(value or "").strip().upper()
    return "C" if text in {"C", "CALL"} else "P" if text in {"P", "PUT"} else None


def quotes_from_eod_rows(rows: Iterable[dict], session: date) -> list[Quote]:
    stamp = datetime.combine(session, time(16, 0), NY).astimezone(UTC).isoformat().replace("+00:00", "Z")
    out: list[Quote] = []
    for r in rows:
        right = _right(r.get("right"))
        try:
            strike = float(r["strike"])
            expiration = str(r["expiration"])[:10]
            if len(expiration) == 8 and expiration.isdigit():
                expiration = f"{expiration[:4]}-{expiration[4:6]}-{expiration[6:]}"
            bid = None if r.get("bid") in (None, "") else float(r["bid"])
            ask = None if r.get("ask") in (None, "") else float(r["ask"])
        except (KeyError, TypeError, ValueError):
            continue
        if right is None or strike <= 0:
            continue
        out.append(Quote(right, strike, expiration, bid, ask, stamp, None))
    return out


class CachedSource:
    """ThetaData access with a plain-file cache: one JSON per symbol per session."""

    def __init__(self, theta_client, cache_dir: Path, max_dte: int = 45,
                 pace_seconds: float = 2.1, option_pace_seconds: float = 0.0):
        self.theta = theta_client
        self.cache_dir = Path(cache_dir)
        self.max_dte = max_dte
        self.requests = 0
        # FREE stock tier: 30 requests per minute.
        self.pace_seconds = pace_seconds
        self.option_pace_seconds = option_pace_seconds

    def chain_rows(self, symbol: str, session: date) -> list[dict]:
        path = self.cache_dir / "option_eod" / symbol.upper() / f"{session.isoformat()}.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        from src.engine.history import RETRY_ATTEMPTS, RETRYABLE_MARKERS
        from src.providers.thetadata import ThetaDataResponseError, ThetaDataUnavailable

        delay = 2.0
        for attempt in range(1, RETRY_ATTEMPTS + 1):
            try:
                payload = self.theta._get_payload(
                    "/option/history/eod",
                    {"symbol": symbol.upper(), "expiration": "*",
                     "start_date": session.strftime("%Y%m%d"),
                     "end_date": session.strftime("%Y%m%d"), "max_dte": self.max_dte},
                )
                break
            except (ThetaDataResponseError, ThetaDataUnavailable) as exc:
                text = str(exc).lower()
                if attempt == RETRY_ATTEMPTS or not any(m in text for m in RETRYABLE_MARKERS):
                    raise
                clock.sleep(delay)
                delay = min(delay * 2, 20.0)
        self.requests += 1
        if self.option_pace_seconds:
            clock.sleep(self.option_pace_seconds)
        rows = _flatten(payload)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rows), encoding="utf-8")
        return rows

    def closes(self, symbol: str, start: date, end: date) -> dict[str, DailyClose]:
        path = self.cache_dir / "stock_eod" / f"{symbol.upper()}_{start.isoformat()}_{end.isoformat()}.json"
        if path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))
            return {d: DailyClose(d, float(c), lt, bool(ah)) for d, c, lt, ah in raw}
        closes = fetch_eod_closes(self.theta, symbol, start, end, pace_seconds=self.pace_seconds)
        self.requests += 1
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps([[c.session_date, c.close, c.last_trade_at, c.after_hours] for c in closes]),
                        encoding="utf-8")
        return {c.session_date: c for c in closes}


# -------------------------------------------------------------------- engine
@dataclass
class BacktestReport:
    settings: dict
    sessions: int
    picks: list[dict]
    daily_scan_stats: list[dict]
    summary: dict


def _session_dates(start: date, end: date, calendar=None) -> list[date]:
    from src.operations.market_calendar import get_xnys_calendar

    cal = calendar or get_xnys_calendar()
    return [d.date() for d in cal.sessions_in_range(start.isoformat(), end.isoformat())]


def run_backtest(theta_client, settings: BacktestSettings, *, calendar=None,
                 progress: Callable[[str], None] | None = None) -> BacktestReport:
    say = progress or (lambda _: None)
    source = CachedSource(theta_client, settings.cache_dir, settings.max_dte,
                          pace_seconds=settings.stock_pace_seconds,
                          option_pace_seconds=settings.option_pace_seconds)
    sessions = _session_dates(settings.start, settings.end, calendar)
    if not sessions:
        raise ValueError("no sessions in range")
    history_start = settings.start - timedelta(days=760)
    close_end = settings.end + timedelta(days=settings.max_dte + 7)
    closes: dict[str, dict[str, DailyClose]] = {}
    for s in settings.symbols:
        try:
            series = source.closes(s, history_start, close_end)
        except Exception as exc:  # a symbol without stock history is skipped, not fatal
            say(f"{s}: no stock history ({type(exc).__name__}: {str(exc)[:200]}); skipped")
            continue
        if not series:
            say(f"{s}: no stock history returned; skipped")
            continue
        closes[s] = series
    symbols = [s for s in settings.symbols if s in closes]
    picks: list[dict] = []
    stats: list[dict] = []
    t0 = clock.time()
    for i, session in enumerate(sessions, start=1):
        asof = datetime.combine(session, DECISION_CLOCK, NY).astimezone(UTC)
        chains = []
        closes_by_symbol = {}
        for s in symbols:
            try:
                rows = source.chain_rows(s, session)
            except Exception as exc:
                say(f"{s} {session}: chain unavailable ({type(exc).__name__})")
                continue
            quotes = quotes_from_eod_rows(rows, session)
            if not quotes:
                continue
            spot = closes[s].get(session.isoformat())
            chains.append(build_chain(s, asof, quotes, snapshot_id=None,
                                      spot=spot.close if spot else None, source="THETADATA_EOD",
                                      min_dte=settings.config.min_dte, max_dte=settings.max_dte))
            closes_by_symbol[s] = [closes[s][d].close for d in sorted(closes[s]) if d < session.isoformat()]
        if not chains:
            continue
        result = run_scan(chains, closes_by_symbol, settings.config, asof=asof, calendar=calendar)
        stats.append({"session": session.isoformat(), "chains": result.chains_scanned,
                      "scored": result.structures_scored, "passed": len(result.passed),
                      "rejections": dict(result.rejections)})
        for c in result.picks:
            rec = c.to_record()
            settle = closes[c.underlying].get(c.expiration)
            pnl = pick_pnl_at(rec, settle.close) if settle else None
            picks.append({
                "session": session.isoformat(), "underlying": c.underlying, "expiration": c.expiration,
                "family": c.family, "shape": c.shape, "description": c.description,
                "entry_cash_usd": c.entry_cash_usd, "max_loss_usd": c.max_loss_usd,
                "mixture_ev_usd": c.conservative_ev_usd, "forecast_ev_usd": c.forecast_ev_usd,
                "implied_ev_usd": c.implied_ev_usd, "stress_ev_usd": c.stress_ev_usd,
                "score": c.score, "pop": c.pop, "p_max_loss": c.p_max_loss,
                "atm_iv": c.atm_iv, "forecast_vol": c.forecast_vol, "event_move_pct": c.event_move_pct,
                "settlement_price": settle.close if settle else None,
                "settlement_after_hours": settle.after_hours if settle else None,
                "pnl_usd": None if pnl is None else round(pnl, 2),
            })
        if progress and (i % 10 == 0 or i == len(sessions)):
            say(f"{i}/{len(sessions)} sessions, {len(picks)} picks, {source.requests} requests, "
                f"{clock.time() - t0:.0f}s")
    summary = summarize(picks, stats, settings, sessions)
    return BacktestReport(settings=_settings_dict(settings), sessions=len(sessions), picks=picks,
                          daily_scan_stats=stats, summary=summary)


def _settings_dict(s: BacktestSettings) -> dict:
    return {"symbols": list(s.symbols), "start": s.start.isoformat(), "end": s.end.isoformat(),
            "max_dte": s.max_dte, "config": s.config.as_dict()}


def summarize(picks: list[dict], stats: list[dict], settings: BacktestSettings,
              sessions: Sequence[date]) -> dict:
    settled = [p for p in picks if p["pnl_usd"] is not None]
    pnls = np.array([p["pnl_usd"] for p in settled], dtype=float)
    by_day: dict[str, list[float]] = defaultdict(list)
    by_month: dict[str, float] = defaultdict(float)
    by_family: dict[str, list[float]] = defaultdict(list)
    by_year: dict[str, list[float]] = defaultdict(list)
    for p in settled:
        by_day[p["expiration"]].append(p["pnl_usd"])
        by_month[p["expiration"][:7]] += p["pnl_usd"]
        by_family[p["family"]].append(p["pnl_usd"])
        by_year[p["expiration"][:4]].append(p["pnl_usd"])
    day_totals = [sum(by_day[d]) for d in sorted(by_day)]
    cumulative = list(np.cumsum(day_totals)) if day_totals else []
    ci = cluster_bootstrap_ci(by_day)
    pops = [p["pop"] for p in settled if p["pop"] is not None]

    def block(values: list[float]) -> dict:
        arr = np.array(values, dtype=float)
        return {"settled": int(len(arr)), "pnl_usd": round(float(arr.sum()), 2),
                "avg_usd": round(float(arr.mean()), 2) if len(arr) else None,
                "hit_rate": round(float((arr > 0).mean()), 4) if len(arr) else None}

    return {
        "engine_version": ENGINE_VERSION,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "period": {"start": sessions[0].isoformat(), "end": sessions[-1].isoformat(),
                   "sessions": len(sessions), "sessions_with_a_pass": sum(1 for s in stats if s["passed"])},
        "symbols": list(settings.symbols),
        "assumptions": {"commission_per_contract": settings.config.cost.commission_per_contract,
                        "slippage_fraction": settings.config.cost.slippage_fraction,
                        "forecast_weight": settings.config.forecast_weight,
                        "decision": "close of each session, EOD NBBO; one pick per underlying, "
                                    f"at most {settings.top_n} per session; hold to expiry"},
        "picks": len(picks), "settled": len(settled), "open": len(picks) - len(settled),
        "expiry_days": len(by_day),
        "total_pnl_usd": round(float(pnls.sum()), 2) if len(pnls) else 0.0,
        "avg_pnl_usd": round(float(pnls.mean()), 2) if len(pnls) else None,
        "avg_pnl_ci95_usd": [round(ci[0], 2), round(ci[1], 2)] if ci else None,
        "hit_rate": round(float((pnls > 0).mean()), 4) if len(pnls) else None,
        "predicted_hit_rate": round(float(np.mean(pops)), 4) if pops else None,
        "predicted_ev_usd": round(float(sum(p["mixture_ev_usd"] for p in settled)), 2),
        "total_risk_usd": round(float(sum(p["max_loss_usd"] for p in settled)), 2),
        "max_drawdown_usd": round(float(drawdown(cumulative)), 2),
        "worst_day_usd": round(float(min(day_totals)), 2) if day_totals else None,
        "best_day_usd": round(float(max(day_totals)), 2) if day_totals else None,
        "worst_month": min(by_month.items(), key=lambda kv: kv[1]) if by_month else None,
        "by_month": {k: round(v, 2) for k, v in sorted(by_month.items())},
        "by_family": {k: block(v) for k, v in sorted(by_family.items())},
        "by_year": {k: block(v) for k, v in sorted(by_year.items())},
        "pass_rate": round(float(np.mean([s["passed"] / max(1, s["scored"]) for s in stats])), 4) if stats else None,
    }


# -------------------------------------------------------------------- output
def write_report(report: BacktestReport, out_dir: Path) -> dict[str, Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {"summary": out_dir / "summary.json", "picks": out_dir / "picks.csv",
             "daily": out_dir / "daily_pnl.csv", "scans": out_dir / "scan_stats.csv"}
    paths["summary"].write_text(json.dumps({"settings": report.settings, "sessions": report.sessions,
                                            **report.summary}, indent=2, default=str), encoding="utf-8")
    if report.picks:
        with paths["picks"].open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(report.picks[0].keys()))
            writer.writeheader()
            writer.writerows(report.picks)
    by_day: dict[str, float] = defaultdict(float)
    for p in report.picks:
        if p["pnl_usd"] is not None:
            by_day[p["expiration"]] += p["pnl_usd"]
    running = 0.0
    with paths["daily"].open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["expiry_date", "pnl_usd", "cumulative_usd"])
        for d in sorted(by_day):
            running += by_day[d]
            writer.writerow([d, round(by_day[d], 2), round(running, 2)])
    with paths["scans"].open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["session", "chains", "scored", "passed", "rejections"])
        for s in report.daily_scan_stats:
            writer.writerow([s["session"], s["chains"], s["scored"], s["passed"], json.dumps(s["rejections"])])
    return paths
