"""Christiania: find defined-risk option trades worth taking, and prove it.

Four screens:
  Today's trades - ranked main-lane trades (7-45 days)
  0DTE           - same/next-day trades on SPY/QQQ, kept separate
  Track record   - every recommended trade settled at expiry
  System         - is data collection and the engine running
"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import streamlit as st

from src.dashboard.read_model import load_command_deck
from src.engine.pipeline import LANE_MAIN, LANE_ZERO_DTE
from src.operations.backup_recovery import inventory_backups_fast
from src.operations.backup_system_status_v1 import read_backup_system_status
from src.operations.release_manifest import read_deployed_commit
from src.operations.saxo_health_status_v1 import probe_saxo_live
from src.operations.saxo_quote_monitor_v1 import read_quote_status
from src.providers.thetadata_control import probe_theta_terminal
import src.ui.design as design
from src.ui.datetime_display import format_local_datetime
from src.engine.chains import NY
from src.engine.ledger import exposure
from src.ui.design import usd
from src.ui.engine_pages import (
    engine_checks, open_risk_cap, read_trades_safe, render_system, render_track_record_page,
    render_trades_page,
)
from src.ui.home_pages import system_checks

ROOT = Path(__file__).resolve().parent
LOGO_PATH = ROOT / "assets" / "christiania_logo.png"

PAGES = ["Today's trades", "0DTE", "Track record", "System"]

st.set_page_config(page_title="Christiania", page_icon="⚓", layout="wide",
                   initial_sidebar_state="auto")
design.inject()


@st.cache_data(show_spinner=False, ttl=30, max_entries=1)
def _cached_theta_health() -> dict:
    return probe_theta_terminal().as_dict()


@st.cache_data(show_spinner=False, ttl=120, max_entries=1)
def _cached_saxo_health() -> dict:
    # Read-only OAuth/user-status probe; never a broker order endpoint.
    return probe_saxo_live().as_dict()


@st.cache_data(show_spinner=False, ttl=90, max_entries=1)
def _cached_saxo_feed_status() -> dict:
    return read_quote_status()


@st.cache_data(show_spinner=False, ttl=90, max_entries=1)
def _cached_recovery_status() -> dict:
    return read_backup_system_status().as_dict()


@st.cache_data(show_spinner="Checking the system…", ttl=180, max_entries=1)
def _cached_system_state():
    snapshot = load_command_deck(include_provider_health=False, deep_integrity=False,
                                 page="System")
    return snapshot, inventory_backups_fast().as_dict()


@st.cache_data(show_spinner=False, ttl=300, max_entries=1)
def _schema_version() -> int | None:
    from src.operations.sqlite_runtime import open_readonly_connection

    try:
        conn = open_readonly_connection()
        try:
            return int(conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0])
        finally:
            conn.close()
    except Exception:
        return None


with st.sidebar:
    if LOGO_PATH.exists():
        st.image(str(LOGO_PATH), width="stretch")
    page = st.radio("Navigation", PAGES, label_visibility="collapsed")
    st.divider()
    risk_budget = st.number_input(
        "Risk limit per trade, $", min_value=0, value=500, step=50,
        help="Only used to show how many lots fit. The engine ranks trades per lot.",
    )
    st.number_input(
        "Open risk cap, $ (0 = none)", min_value=0, step=500, key="open_risk_cap",
        value=int(open_risk_cap()),
        help="Sum of max loss across your open recorded trades. Cards warn when a trade would "
             "exceed it. Default from CHRISTIANIA_MAX_OPEN_RISK_USD.",
    )
    _trades = read_trades_safe()
    if _trades:
        _ex = exposure(_trades, today=datetime.now(UTC).astimezone(NY).date())
        st.caption(f"Open risk {usd(_ex.open_risk_usd)} in {_ex.open_trades} trade"
                   f"{'s' if _ex.open_trades != 1 else ''}")
    if st.button("Refresh data", width="stretch"):
        st.cache_data.clear()
        st.rerun()
    sha = read_deployed_commit()
    schema = _schema_version()
    st.caption(
        (f"Build [{sha[:8]}](https://github.com/Drekkie86/trade-log/commit/{sha})"
         if sha else "Build identity unavailable")
        + (f", schema v{schema}" if schema is not None else "")
    )

if page == "Today's trades":
    render_trades_page(LANE_MAIN, risk_budget=float(risk_budget) or None)
elif page == "0DTE":
    render_trades_page(LANE_ZERO_DTE, risk_budget=float(risk_budget) or None)
elif page == "Track record":
    render_track_record_page()
else:
    snapshot, backups = _cached_system_state()
    if not snapshot.get("ready"):
        design.html('<div class="chr-head"><h1>System</h1></div>')
        st.error(f"Christiania cannot open the database: {snapshot.get('reason')}")
        st.stop()
    rows = system_checks(
        snapshot, _cached_theta_health(), backups,
        saxo=_cached_saxo_health(), recovery=_cached_recovery_status(),
        feed=_cached_saxo_feed_status(),
    ) + engine_checks(datetime.now(UTC))
    clock = snapshot.get("market_clock", {}) or {}
    render_system(
        rows,
        next_collection=format_local_datetime(clock.get("next_sample_at")),
        collecting=str(clock.get("state") or "").upper() == "ACTIVE_SAMPLE_WINDOW",
    )
