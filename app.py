"""Christiania: find defined-risk option trades worth taking, and prove it.

Four screens:
  Today's trades - ranked main-lane trades (7-45 days)
  0DTE           - same/next-day trades on SPY/QQQ, kept separate
  Track record   - every recommended trade settled at expiry
  System         - is data collection and the engine running
"""
from __future__ import annotations

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
from src.ui import inject_christiania_theme
from src.ui.engine_pages import (
    render_trades_page, render_track_record_page, ny_time, _read_scan,
)
from src.ui.home_pages import render_system_page

ROOT = Path(__file__).resolve().parent
LOGO_PATH = ROOT / "assets" / "christiania_logo.png"

PAGES = {
    "💰 Today's trades": "trades",
    "⚡ 0DTE": "zero_dte",
    "📊 Track record": "record",
    "🩺 System": "system",
}

st.set_page_config(page_title="Christiania", page_icon="⚓", layout="wide",
                   initial_sidebar_state="auto")
inject_christiania_theme()


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


@st.cache_data(show_spinner="Loading system status…", ttl=180, max_entries=1)
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
    st.divider()
    choice = st.radio("Navigation", list(PAGES), label_visibility="collapsed")
    page = PAGES[choice]
    st.divider()
    risk_budget = st.number_input(
        "Max risk per trade ($)", min_value=0.0, value=500.0, step=50.0,
        help="Used only to show how many contracts fit. The engine ranks trades per lot.",
    )
    if st.button("↻ Refresh", width="stretch"):
        st.cache_data.clear()
        st.rerun()
    sha = read_deployed_commit()
    schema = _schema_version()
    st.caption(
        (f"Deployed [{sha[:8]}](https://github.com/Drekkie86/trade-log/commit/{sha})"
         if sha else "Deployed build: identity unavailable")
        + (f" · schema v{schema}" if schema is not None else "")
    )

if page == "trades":
    render_trades_page(LANE_MAIN, risk_budget=risk_budget or None)
elif page == "zero_dte":
    render_trades_page(LANE_ZERO_DTE, risk_budget=risk_budget or None)
elif page == "record":
    render_track_record_page()
else:
    snapshot, backups = _cached_system_state()
    if not snapshot.get("ready"):
        st.error(f"Christiania cannot open the database: {snapshot.get('reason')}")
        st.stop()
    render_system_page(
        snapshot, _cached_theta_health(), backups,
        saxo=_cached_saxo_health(), recovery=_cached_recovery_status(),
        feed=_cached_saxo_feed_status(),
    )
    st.markdown("#### Trade engine")
    for lane, label in ((LANE_MAIN, "Main scan"), (LANE_ZERO_DTE, "0DTE scan")):
        try:
            scan = _read_scan(lane, None)
        except Exception as exc:  # engine tables absent before migration 039
            st.caption(f"{label}: unavailable ({type(exc).__name__})")
            continue
        if scan is None:
            st.caption(f"{label}: no scan yet")
        else:
            st.caption(
                f"{label}: {scan['status'].lower()} at {ny_time(scan['asof_at'])} — "
                f"{scan['structures_scored']:,} trades priced, {scan['passed_count']} passed"
            )
