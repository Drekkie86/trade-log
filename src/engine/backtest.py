"""Historical backtest of the engine on ThetaData end-of-day option chains.

Two phases over the cached EOD chains:

* warm-up: for every session in the WARMUP_CALENDAR_DAYS before ``start`` the
  30-day implied vol is recorded (one chain per symbol per session), so the
  risk premium has a history to be measured on when scoring starts;
* scoring: for every session in [start, end] each symbol's chain is built from
  the EOD report (last NBBO at report time, so the "decision" is taken at the
  close), the same ``run_scan`` the daemon runs is applied with that session's
  lambda, the best structure per underlying is frozen (at most ``top_n``; a
  name with an unexpired pick is skipped), and each pick settles at expiry on
  the stock EOD close.

The report splits the picks at ``oos_start``: everything before it is the
calibration window the engine was designed against, everything from it on is
the out-of-sample test, judged by the pre-registered criteria in
``evaluate_criteria`` (written before the test data was seen; see
docs/reviews). A single-slot account path (one open position at a time, the
best-scored pick when the slot is free) is derived from the same picks.
"""
from __future__ import annotations

import csv
import json
import math
import os
import time as clock
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Callable, Sequence

import numpy as np

from src.engine import ENGINE_VERSION
from src.engine.chains import NY, build_chain
from src.engine.eod import fetch_eod_chain_rows, quotes_from_eod_rows
from src.engine.history import (
    DailyClose, adjusted_closes, fetch_eod_closes, split_factor_between,
)
from src.engine.ledger import MIN_EXPIRY_DAYS_FOR_VERDICT, cluster_bootstrap_ci, drawdown, pick_pnl_at
from src.engine.models import ModelUnavailable, RiskPremium, estimate_risk_premium
from src.engine.pipeline import EngineConfig, main_config, run_scan
from src.engine.premium import iv_point_from_rows

__all__ = ["BacktestSettings", "run_backtest", "summarize", "write_report", "quotes_from_eod_rows",
           "evaluate_criteria", "single_slot_path"]

DECISION_CLOCK = time(15, 59, 30)
WARMUP_CALENDAR_DAYS = 400            # ~275 sessions: MIN_PREMIUM_OBSERVATIONS + horizon + slack

# Pre-registered pass criteria for the out-of-sample window (2026-11-08, before
# any out-of-sample result was seen). All three must hold, over at least
# MIN_EXPIRY_DAYS_FOR_VERDICT expiry days:
#   1. the cluster-bootstrap 95 % range of the average pick excludes zero from above;
#   2. the realised hit rate is within PASS_MAX_HIT_RATE_GAP of the predicted one;
#   3. the realised full-loss rate is at most PASS_MAX_FULL_LOSS_GAP above the predicted one.
PASS_MAX_HIT_RATE_GAP = 0.05
PASS_MAX_FULL_LOSS_GAP = 0.05


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
    oos_start: date | None = date(2025, 1, 1)

    @property
    def top_n(self) -> int:
        return self.config.top_n


# ------------------------------------------------------------------ provider
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

    @staticmethod
    def _read(path: Path):
        """Cached payload, or None when the file is missing or was left half-written
        (a run stopped mid-write); a damaged file is removed so it is fetched again."""
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            path.unlink(missing_ok=True)
            return None

    @staticmethod
    def _write(path: Path, payload) -> None:
        """Write to a sibling temp file and rename, so a cache entry is whole or absent."""
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(tmp, path)

    def chain_rows(self, symbol: str, session: date) -> list[dict]:
        path = self.cache_dir / "option_eod" / symbol.upper() / f"{session.isoformat()}.json"
        cached = self._read(path)
        if cached is not None:
            return cached
        rows = fetch_eod_chain_rows(self.theta, symbol, session, max_dte=self.max_dte)
        self.requests += 1
        if self.option_pace_seconds:
            clock.sleep(self.option_pace_seconds)
        self._write(path, rows)
        return rows

    def closes(self, symbol: str, start: date, end: date,
               problems: list[str] | None = None) -> dict[str, DailyClose]:
        path = self.cache_dir / "stock_eod" / f"{symbol.upper()}_{start.isoformat()}_{end.isoformat()}.json"
        raw = self._read(path)
        if raw is not None:
            return {d: DailyClose(d, float(c), lt, bool(ah)) for d, c, lt, ah in raw}
        closes = fetch_eod_closes(self.theta, symbol, start, end, pace_seconds=self.pace_seconds,
                                  problems=problems)
        self.requests += 1
        self._write(path, [[c.session_date, c.close, c.last_trade_at, c.after_hours] for c in closes])
        return {c.session_date: c for c in closes}


TERMINAL_MARKERS = ("478", "invalid session", "could not reach", "login", "not logged")
CONSECUTIVE_FAILURE_LIMIT = 25
TERMINAL_WAITS = (30.0, 60.0, 120.0)


def is_terminal_failure(exc: BaseException) -> bool:
    """A dead or logged-out Theta Terminal, as opposed to a session without data."""
    from src.providers.thetadata import ThetaDataUnavailable

    text = str(exc).lower()
    return isinstance(exc, ThetaDataUnavailable) or any(m in text for m in TERMINAL_MARKERS)


class BacktestAborted(RuntimeError):
    pass


# -------------------------------------------------------------------- engine
@dataclass
class BacktestReport:
    settings: dict
    sessions: int
    picks: list[dict]
    daily_scan_stats: list[dict]
    premium_rows: list[dict]
    summary: dict


def _session_dates(start: date, end: date, calendar=None) -> list[date]:
    from src.operations.market_calendar import get_xnys_calendar

    cal = calendar or get_xnys_calendar()
    if end < start:
        return []
    return [d.date() for d in cal.sessions_in_range(start.isoformat(), end.isoformat())]


class _Fetcher:
    """Chain fetch with the terminal-failure protocol: wait and retry a dead
    terminal three times, then abort; count other failures."""

    def __init__(self, source: CachedSource, say: Callable[[str], None]):
        self.source = source
        self.say = say
        self.aborted_reason: str | None = None
        self.failures: list[str] = []
        self.consecutive = 0

    def rows(self, symbol: str, session: date, *, tolerant: bool) -> list[dict] | None:
        for wait in (*TERMINAL_WAITS, None):
            try:
                rows = self.source.chain_rows(symbol, session)
                self.consecutive = 0
                return rows
            except Exception as exc:
                if is_terminal_failure(exc) and wait is not None:
                    self.say(f"terminal failure ({str(exc)[:120]}); waiting {wait:.0f}s")
                    clock.sleep(wait)
                    continue
                if is_terminal_failure(exc):
                    self.aborted_reason = (f"Theta Terminal unavailable at {symbol} {session}: "
                                           f"{str(exc)[:200]}. Restart it and rerun; cached sessions are kept.")
                    return None
                self.failures.append(f"{symbol} {session}: {str(exc)[:160]}")
                self.say(f"{symbol} {session}: chain unavailable ({str(exc)[:120]})")
                if not tolerant:
                    self.consecutive += 1
                    if self.consecutive >= CONSECUTIVE_FAILURE_LIMIT:
                        self.aborted_reason = (f"{self.consecutive} chain requests failed in a row "
                                               f"(last: {self.failures[-1]}). Check the terminal and rerun.")
                return None
        return None


def run_backtest(theta_client, settings: BacktestSettings, *, calendar=None,
                 progress: Callable[[str], None] | None = None) -> BacktestReport:
    say = progress or (lambda _: None)
    source = CachedSource(theta_client, settings.cache_dir, settings.max_dte,
                          pace_seconds=settings.stock_pace_seconds,
                          option_pace_seconds=settings.option_pace_seconds)
    sessions = _session_dates(settings.start, settings.end, calendar)
    if not sessions:
        raise ValueError("no sessions in range")
    warmup = _session_dates(settings.start - timedelta(days=WARMUP_CALENDAR_DAYS),
                            settings.start - timedelta(days=1), calendar)
    history_start = (warmup[0] if warmup else settings.start) - timedelta(days=30)
    today = datetime.now(UTC).astimezone(NY).date()
    close_end = min(settings.end + timedelta(days=settings.max_dte + 7), today)
    closes: dict[str, dict[str, DailyClose]] = {}
    history_problems: list[str] = []
    for s in settings.symbols:
        try:
            series = source.closes(s, history_start, close_end, problems=history_problems)
        except Exception as exc:  # a symbol without stock history is skipped, not fatal
            say(f"{s}: no stock history ({type(exc).__name__}: {str(exc)[:200]}); skipped")
            continue
        if not series:
            say(f"{s}: no stock history returned; skipped")
            continue
        closes[s] = series
        first, last = min(series), max(series)
        say(f"{s}: {len(series)} closes {first}..{last}")
    for problem in history_problems:
        say(f"history chunk skipped: {problem}")
    symbols = [s for s in settings.symbols if s in closes]
    fetcher = _Fetcher(source, say)
    iv_points: dict[str, list[tuple[str, float]]] = {s: [] for s in symbols}
    warmup_with_chains = 0
    t0 = clock.time()

    def record_iv(symbol: str, session: date, rows: list[dict]) -> float | None:
        point = iv_point_from_rows(rows, session)
        if point is not None:
            iv_points[symbol].append((session.isoformat(), point))
        return point

    # Phase 1: implied-vol history. Failures here are tolerated (the tier may not
    # serve the oldest sessions); a dead terminal still aborts.
    say(f"warm-up: {len(warmup)} sessions of implied-vol history before {settings.start}")
    for i, session in enumerate(warmup, start=1):
        for s in symbols:
            rows = fetcher.rows(s, session, tolerant=True)
            if fetcher.aborted_reason:
                break
            if rows:
                warmup_with_chains += 1
                record_iv(s, session, rows)
        if fetcher.aborted_reason:
            say(f"ABORTED: {fetcher.aborted_reason}")
            break
        if progress and (i % 25 == 0 or i == len(warmup)):
            say(f"warm-up {i}/{len(warmup)} sessions, {source.requests} requests, "
                f"{clock.time() - t0:.0f}s")

    # Phase 2: score.
    sessions_with_chains = 0
    open_until: dict[str, str] = {}
    picks: list[dict] = []
    stats: list[dict] = []
    premium_rows: list[dict] = []
    for i, session in enumerate(sessions, start=1):
        if fetcher.aborted_reason:
            break
        asof = datetime.combine(session, DECISION_CLOCK, NY).astimezone(UTC)
        iso = session.isoformat()
        chains = []
        premiums: dict[str, RiskPremium | None] = {}
        for s in symbols:
            rows = fetcher.rows(s, session, tolerant=False)
            if fetcher.aborted_reason:
                break
            if rows is None:
                continue
            sessions_with_chains += 1
            iv_today = record_iv(s, session, rows)
            quotes = quotes_from_eod_rows(rows, session)
            if not quotes:
                continue
            dated = [(d, closes[s][d].close) for d in sorted(closes[s]) if d < iso]
            adjusted = list(zip((d for d, _ in dated), adjusted_closes(dated)))
            try:
                premiums[s] = estimate_risk_premium(iv_points[s], adjusted, before=iso)
            except ModelUnavailable:
                premiums[s] = None
            prem = premiums[s]
            premium_rows.append({"session": iso, "underlying": s, "iv30": iv_today,
                                 "ratio": None if prem is None else round(prem.ratio, 4),
                                 "observations": None if prem is None else prem.observations})
            spot = closes[s].get(iso)
            chains.append(build_chain(s, asof, quotes, snapshot_id=None,
                                      spot=spot.close if spot else None, source="THETADATA_EOD",
                                      min_dte=settings.config.min_dte, max_dte=settings.max_dte))
        if fetcher.aborted_reason:
            say(f"ABORTED: {fetcher.aborted_reason}")
            break
        if not chains:
            continue
        open_names = {s for s, exp in open_until.items() if exp >= iso}
        result = run_scan(chains, premiums, settings.config, asof=asof, calendar=calendar,
                          open_underlyings=open_names)
        stats.append({"session": iso, "chains": result.chains_scanned,
                      "scored": result.structures_scored, "passed": len(result.passed),
                      "rejections": dict(result.rejections)})
        for c in result.picks:
            rec = c.to_record()
            open_until[c.underlying] = c.expiration
            settle = closes[c.underlying].get(c.expiration)
            factor = split_factor_between(
                [(d, closes[c.underlying][d].close) for d in sorted(closes[c.underlying])
                 if d <= c.expiration], iso, c.expiration) if settle else 1.0
            pnl = pick_pnl_at(rec, settle.close * factor) if settle else None
            picks.append({
                "session": iso, "underlying": c.underlying, "expiration": c.expiration,
                "family": c.family, "shape": c.shape, "description": c.description,
                "entry_cash_usd": c.entry_cash_usd, "max_loss_usd": c.max_loss_usd,
                "ev_usd": c.ev_usd, "implied_ev_usd": c.implied_ev_usd, "stress_ev_usd": c.stress_ev_usd,
                "score": c.score, "pop": c.pop, "p_max_loss": c.p_max_loss,
                "atm_iv": c.atm_iv, "premium_ratio": c.premium_ratio,
                "premium_observations": c.premium_observations, "event_move_pct": c.event_move_pct,
                "settlement_price": settle.close * factor if settle else None,
                "split_factor": factor if settle else None,
                "settlement_after_hours": settle.after_hours if settle else None,
                "pnl_usd": None if pnl is None else round(pnl, 2),
            })
        if progress and (i % 10 == 0 or i == len(sessions)):
            say(f"{i}/{len(sessions)} sessions, {len(picks)} picks, {source.requests} requests, "
                f"{clock.time() - t0:.0f}s")
    summary = summarize(picks, stats, settings, sessions)
    summary["coverage"] = {
        "sessions_requested": len(sessions),
        "sessions_with_chains": sessions_with_chains,
        "warmup_sessions_requested": len(warmup),
        "warmup_sessions_with_chains": warmup_with_chains,
        "iv_points": {s: len(v) for s, v in iv_points.items()},
        "chain_failures": len(fetcher.failures),
        "chain_failure_examples": fetcher.failures[:5],
        "history_chunks_skipped": history_problems,
        "first_pick": min((p["session"] for p in picks), default=None),
        "last_pick": max((p["session"] for p in picks), default=None),
        "aborted_reason": fetcher.aborted_reason,
    }
    return BacktestReport(settings=_settings_dict(settings), sessions=len(sessions), picks=picks,
                          daily_scan_stats=stats, premium_rows=premium_rows, summary=summary)


def _settings_dict(s: BacktestSettings) -> dict:
    return {"symbols": list(s.symbols), "start": s.start.isoformat(), "end": s.end.isoformat(),
            "max_dte": s.max_dte, "oos_start": s.oos_start.isoformat() if s.oos_start else None,
            "config": s.config.as_dict()}


# ------------------------------------------------------------------- summary
def _block(settled: list[dict]) -> dict:
    """Performance and calibration of a set of settled picks."""
    pnls = np.array([float(p["pnl_usd"]) for p in settled], dtype=float)
    by_day: dict[str, list[float]] = defaultdict(list)
    by_month: dict[str, float] = defaultdict(float)
    by_family: dict[str, list[dict]] = defaultdict(list)
    by_symbol: dict[str, list[dict]] = defaultdict(list)
    for p in settled:
        by_day[p["expiration"]].append(float(p["pnl_usd"]))
        by_month[p["expiration"][:7]] += float(p["pnl_usd"])
        by_family[p["family"]].append(p)
        by_symbol[p["underlying"]].append(p)
    day_totals = [sum(by_day[d]) for d in sorted(by_day)]
    cumulative = list(np.cumsum(day_totals)) if day_totals else []
    ci = cluster_bootstrap_ci(by_day)
    pops = [float(p["pop"]) for p in settled if p.get("pop") is not None and math.isfinite(float(p["pop"]))]
    pmls = [float(p["p_max_loss"]) for p in settled
            if p.get("p_max_loss") is not None and math.isfinite(float(p["p_max_loss"]))]
    risk = float(sum(float(p["max_loss_usd"]) for p in settled))
    full = sum(1 for p in settled if float(p["pnl_usd"]) <= -0.95 * float(p["max_loss_usd"]))

    def sub(items: list[dict]) -> dict:
        arr = np.array([float(p["pnl_usd"]) for p in items], dtype=float)
        r = float(sum(float(p["max_loss_usd"]) for p in items))
        return {"settled": len(items), "pnl_usd": round(float(arr.sum()), 2),
                "avg_usd": round(float(arr.mean()), 2),
                "hit_rate": round(float((arr > 0).mean()), 4),
                "predicted_hit_rate": round(float(np.mean([float(p["pop"]) for p in items])), 4),
                "predicted_ev_usd": round(float(sum(float(p["ev_usd"]) for p in items)), 2),
                "return_on_risk": round(float(arr.sum()) / r, 4) if r else None}

    return {
        "settled": len(settled),
        "expiry_days": len(by_day),
        "total_pnl_usd": round(float(pnls.sum()), 2) if len(pnls) else 0.0,
        "avg_pnl_usd": round(float(pnls.mean()), 2) if len(pnls) else None,
        "avg_pnl_ci95_usd": [round(ci[0], 2), round(ci[1], 2)] if ci else None,
        "hit_rate": round(float((pnls > 0).mean()), 4) if len(pnls) else None,
        "predicted_hit_rate": round(float(np.mean(pops)), 4) if pops else None,
        "max_loss_rate": round(full / len(pnls), 4) if len(pnls) else None,
        "predicted_max_loss_rate": round(float(np.mean(pmls)), 4) if pmls else None,
        "predicted_ev_usd": round(float(sum(float(p["ev_usd"]) for p in settled)), 2),
        "total_risk_usd": round(risk, 2),
        "return_on_risk": round(float(pnls.sum()) / risk, 4) if risk else None,
        "max_drawdown_usd": round(float(drawdown(cumulative)), 2),
        "worst_day_usd": round(float(min(day_totals)), 2) if day_totals else None,
        "best_day_usd": round(float(max(day_totals)), 2) if day_totals else None,
        "worst_month": min(by_month.items(), key=lambda kv: kv[1]) if by_month else None,
        "by_month": {k: round(v, 2) for k, v in sorted(by_month.items())},
        "by_family": {k: sub(v) for k, v in sorted(by_family.items())},
        "by_symbol": {k: sub(v) for k, v in sorted(by_symbol.items())},
        "first_session": min((p["session"] for p in settled), default=None),
        "last_session": max((p["session"] for p in settled), default=None),
    }


def evaluate_criteria(block: dict) -> dict:
    """The pre-registered out-of-sample test. Mechanical; no judgement calls."""
    days = int(block.get("expiry_days") or 0)
    ci = block.get("avg_pnl_ci95_usd")
    hit, phit = block.get("hit_rate"), block.get("predicted_hit_rate")
    mlr, pmlr = block.get("max_loss_rate"), block.get("predicted_max_loss_rate")
    enough = days >= MIN_EXPIRY_DAYS_FOR_VERDICT and ci is not None and hit is not None \
        and phit is not None and mlr is not None and pmlr is not None
    checks = {
        "expiry_days": {"value": days, "required": MIN_EXPIRY_DAYS_FOR_VERDICT,
                        "pass": days >= MIN_EXPIRY_DAYS_FOR_VERDICT},
        "ci_lower_bound_above_zero": {"value": None if ci is None else ci[0],
                                      "pass": bool(ci is not None and ci[0] > 0)},
        "hit_rate_gap": {"value": None if hit is None or phit is None else round(abs(hit - phit), 4),
                         "limit": PASS_MAX_HIT_RATE_GAP,
                         "pass": bool(hit is not None and phit is not None
                                      and abs(hit - phit) <= PASS_MAX_HIT_RATE_GAP)},
        "full_loss_rate_excess": {"value": None if mlr is None or pmlr is None else round(mlr - pmlr, 4),
                                  "limit": PASS_MAX_FULL_LOSS_GAP,
                                  "pass": bool(mlr is not None and pmlr is not None
                                               and mlr - pmlr <= PASS_MAX_FULL_LOSS_GAP)},
    }
    if not enough:
        verdict = "INSUFFICIENT"
    elif all(c["pass"] for c in checks.values()):
        verdict = "PASS"
    else:
        verdict = "FAIL"
    return {"verdict": verdict, "checks": checks,
            "statement": "Pre-registered 2026-11-08: bootstrap 95% lower bound > 0, hit-rate gap "
                         f"<= {PASS_MAX_HIT_RATE_GAP:.0%}, full-loss rate at most "
                         f"{PASS_MAX_FULL_LOSS_GAP:.0%} above predicted, over >= "
                         f"{MIN_EXPIRY_DAYS_FOR_VERDICT} expiry days."}


def single_slot_path(picks: list[dict]) -> list[dict]:
    """One open position at a time: when the slot is free, take the session's
    best-scored settled pick and hold it to expiry. The account-sized view."""
    by_session: dict[str, list[dict]] = defaultdict(list)
    for p in picks:
        if p.get("pnl_usd") is not None:
            by_session[p["session"]].append(p)
    busy_until: str | None = None
    out: list[dict] = []
    for session in sorted(by_session):
        if busy_until is not None and session <= busy_until:
            continue
        best = max(by_session[session], key=lambda p: (float(p["score"]), float(p["ev_usd"])))
        out.append(best)
        busy_until = best["expiration"]
    return out


def summarize(picks: list[dict], stats: list[dict], settings: BacktestSettings,
              sessions: Sequence[date]) -> dict:
    settled = [p for p in picks if p["pnl_usd"] is not None]
    oos = settings.oos_start.isoformat() if settings.oos_start else None
    calibration = [p for p in settled if oos is None or p["session"] < oos]
    out_of_sample = [p for p in settled if oos is not None and p["session"] >= oos]
    whole = _block(settled)
    oos_block = _block(out_of_sample)
    return {
        "engine_version": ENGINE_VERSION,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "period": {"start": sessions[0].isoformat(), "end": sessions[-1].isoformat(),
                   "sessions": len(sessions), "sessions_with_a_pass": sum(1 for s in stats if s["passed"])},
        "symbols": list(settings.symbols),
        "assumptions": {"commission_per_contract": settings.config.cost.commission_per_contract,
                        "slippage_fraction": settings.config.cost.slippage_fraction,
                        "decision": "close of each session, EOD NBBO; one pick per underlying, "
                                    f"at most {settings.top_n} per session; one open pick per "
                                    "underlying at a time; hold to expiry",
                        "oos_start": oos},
        "picks": len(picks), "settled": len(settled), "open": len(picks) - len(settled),
        **{k: v for k, v in whole.items() if k not in ("settled",)},
        "calibration": _block(calibration),
        "out_of_sample": oos_block,
        "criteria": evaluate_criteria(oos_block),
        "single_slot": {"all": _block(single_slot_path(settled)),
                        "out_of_sample": _block(single_slot_path(out_of_sample))},
        "pass_rate": round(float(np.mean([s["passed"] / max(1, s["scored"]) for s in stats])), 4) if stats else None,
    }


# -------------------------------------------------------------------- output
def write_report(report: BacktestReport, out_dir: Path) -> dict[str, Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {"summary": out_dir / "summary.json", "picks": out_dir / "picks.csv",
             "daily": out_dir / "daily_pnl.csv", "scans": out_dir / "scan_stats.csv",
             "premium": out_dir / "risk_premium.csv"}
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
    with paths["premium"].open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["session", "underlying", "iv30", "ratio", "observations"])
        writer.writeheader()
        writer.writerows(report.premium_rows)
    return paths
