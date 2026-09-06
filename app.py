from __future__ import annotations

from pathlib import Path
import time

from src.decision import (
    assess_exit_monitor,
    assess_market_quality,
    assess_prospective_evidence,
    build_candidate_review_board,
    build_risk_plan,
    resolve_candidate_governance,
    resolve_time_to_expiry,
    run_candidate_model_dossier,
)

import pandas as pd
import streamlit as st

from src.dashboard.read_model import load_command_deck
from src.operations.backup_recovery import inventory_backups
from src.operations.burn_in import read_burn_in_samples, summarize_burn_in
from src.operations.release_manifest import build_release_manifest
from src.operations.v1_readiness import assess_v1_readiness
from src.research.cash_settled_universe import cash_settled_research_universe
from src.research.settlement_policy import cash_settled_allowlist, classify_settlement
from src.quant.bench import run_vanilla_bench
from src.quant.registry import catalog as quant_model_catalog
from src.quant.types import QuantInputError, VanillaOption
from src.ui import (
    badge,
    card,
    hero,
    inject_christiania_theme,
    section_heading,
    status_dot,
    chart_note,
    calibration_evidence_state,
    hypothesis_label,
    model_label,
    provider_label,
)
from src.version import CHRISTIANIA_VERSION

ROOT = Path(__file__).resolve().parent
LOGO_PATH = ROOT / "assets" / "christiania_logo.png"
QUANT_BENCH_LEGACY_LABEL = "Quant Bench"  # retained for V1 compatibility contracts

COLUMN_LABELS = {
    "id": "ID",
    "scheduled_for": "Scheduled for",
    "started_at": "Started at",
    "completed_at": "Completed at",
    "status": "Status",
    "research_run_id": "Research run ID",
    "proposals_count": "Proposals",
    "admitted_count": "Admitted",
    "blocked_count": "Blocked",
    "outcome_mark_count": "Marks this cycle",
    "error_type": "Error type",
    "model_key": "Backend model ID",
    "model_version": "Version",
    "model_family": "Model family",
    "governance_role": "Governance role",
    "evidence_use_enabled": "Evidence use enabled",
    "admission_enabled": "Admission enabled",
    "decision_enabled": "Decision enabled",
    "hypothesis_key": "Backend hypothesis ID",
    "primary_unit": "Primary unit",
    "primary_metric": "Primary metric",
    "minimum_independent_dates": "Minimum independent dates",
    "hypothesis_state": "Hypothesis state",
    "us_session_date": "Session date",
    "underlying": "Underlying",
    "expiration": "Expiration",
    "strike": "Strike",
    "right": "Right",
    "iv_residual": "IV residual",
    "abs_iv_residual": "Absolute IV residual",
    "surfaced_direction": "Surfaced direction",
    "scanner_version": "Scanner version",
    "target_strike": "Target strike",
    "anomaly_direction": "Anomaly direction",
    "proposal_state": "Proposal state",
    "reason_code": "Reason",
    "structure_id": "Structure",
    "max_theoretical_loss_minor": "Max theoretical loss (minor units)",
    "risk_currency": "Risk currency",
    "created_at": "Created at",
    "surfaced_at": "Surfaced at",
    "universe_status": "Universe status",
    "structure_version": "Structure version",
    "admission_label": "Admission label",
    "candidate_id": "Candidate ID",
    "observed_at": "Observed at",
    "provider": "Provider",
    "structure_mark_usd_minor": "Structure mark (USD cents)",
    "gross_pnl_usd_minor": "Gross P&L (USD cents)",
    "estimated_net_pnl_usd_minor": "Estimated net P&L (USD cents)",
    "gross_pnl_eur_minor": "Gross P&L (EUR cents)",
    "estimated_net_pnl_eur_minor": "Estimated net P&L (EUR cents)",
    "quality_state": "Mark quality",
    "measurement_role": "Measurement role",
    "outcome_eligible": "Outcome eligible",
    "mark_count": "Total shadow marks",
    "latest_mark_at": "Latest mark",
    "latest_estimated_net_pnl_eur_minor": "Latest est. net P&L (EUR cents)",
    "latest_measurement_role": "Latest measurement role",
    "latest_outcome_eligible": "Latest outcome eligible",
    "failure_type": "Failure type",
    "samples": "Samples",
    "blocking": "Blocking",
    "category": "Category",
    "detail": "Detail",
    "name": "Check",
    "state": "State",
    "path": "Path",
    "size_bytes": "Size (bytes)",
    "schema_version": "Schema version",
    "integrity": "Integrity",
    "fk_violation_count": "FK violations",
    "age_hours": "Age (hours)",
    "valid": "Valid",
    "model_id": "Model",
    "family": "Family",
    "role": "Role",
    "notes": "Notes",
    "runtime_state": "Runtime state",
    "research_rank": "Research rank",
    "settlement_state": "Settlement state",
    "settlement_type": "Settlement type",
    "exercise_style_policy": "Exercise style",
    "physical_delivery_risk": "Physical delivery risk",
    "risk_plan_state": "Risk-plan state",
    "planned_loss_trigger_eur": "Planned loss trigger (€)",
    "bankroll_fraction": "Bankroll fraction",
    "decision_desk_disposition": "Decision Desk disposition",
    "decision_blocker_count": "Blockers",
    "admission_decision": "Shadow admission",
    "admission_reason_code": "Admission reason",
    "reserved_risk_eur_minor": "Reserved risk (EUR cents)",
    "estimated_cost_eur_minor": "Estimated costs (EUR cents)",
    "target_bid": "Target bid",
    "target_ask": "Target ask",
    "target_implied_volatility": "Target IV",
    "residual_threshold": "Residual threshold",
    "model_input_complete": "Model inputs complete",
    "fair_value_per_share": "Fair value / share",
    "fair_value_per_contract": "Fair value / contract",
    "market_entry_per_share": "Market entry / share",
    "model_minus_entry_per_contract": "Model − entry / contract",
    "candidate_governance_state": "Candidate governance",
    "market_quality_state": "Market quality",
    "quote_age_seconds": "Quote age (seconds)",
    "spread_to_mid": "Spread / mid",
    "prospective_evidence_state": "Prospective evidence",
    "time_to_expiry_state": "TTE state",
    "research_action": "Research action",
    "primary_research_model": "Primary research model",
    "contract_identity_state": "Contract identity",
    "multiplier_state": "Multiplier state",
    "similar_independent_dates": "Similar independent dates",
    "similar_candidate_count": "Similar candidates",
    "similar_validated_outcomes": "Similar validated outcomes",
    "similar_profitable_outcomes": "Similar profitable outcomes",
    "similar_unprofitable_outcomes": "Similar unprofitable outcomes",
    "similar_mean_net_pnl_eur_minor": "Similar mean net P&L (EUR cents)",
    "collection_status": "Collection status",
    "retry_count": "Retries",
    "was_recovered": "Recovered sample",
}


def _human_column_name(name: str) -> str:
    return COLUMN_LABELS.get(name, name.replace("_", " ").strip().title())


def _humanize_dataframe(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()

    if "hypothesis_key" in frame.columns:
        position = frame.columns.get_loc("hypothesis_key")
        frame.insert(
            position,
            "hypothesis_display_name",
            frame["hypothesis_key"].map(hypothesis_label),
        )

    if "model_key" in frame.columns:
        position = frame.columns.get_loc("model_key")
        frame.insert(
            position,
            "model_display_name",
            frame["model_key"].map(model_label),
        )

    if "provider" in frame.columns:
        frame["provider"] = frame["provider"].map(provider_label)

    labels = {
        name: _human_column_name(str(name))
        for name in frame.columns
    }
    labels["hypothesis_display_name"] = "Hypothesis"
    labels["model_display_name"] = "Model"
    return frame.rename(columns=labels)


def _fmt_latency_ms(value) -> str:
    if value is None:
        return "—"
    try:
        return f"{_fmt_number(float(value), decimals=1)} ms"
    except (TypeError, ValueError):
        return "—"


def _fmt_number(value, *, decimals: int | None = None) -> str:
    """Human-readable Belgian-style number formatting for UI display only."""
    if value is None:
        return "—"
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return str(value)

    if decimals is None:
        decimals = 0 if numeric.is_integer() else 2

    rendered = f"{numeric:,.{decimals}f}"
    # Python emits 12,345.67. Christiania displays 12.345,67.
    return rendered.replace(",", "§").replace(".", ",").replace("§", ".")


def _fmt_count(value) -> str:
    return _fmt_number(int(value or 0), decimals=0)


def _visual_note(text: str) -> None:
    chart_note(text)


def _selection_rows(event) -> list[int]:
    if event is None:
        return []
    try:
        selection = event.get("selection", {})
        rows = selection.get("rows", [])
        return [int(row) for row in rows]
    except (AttributeError, TypeError, ValueError):
        return []


def _vega_selected_points(event, name: str) -> list[dict]:
    if event is None:
        return []
    try:
        selection = event.get("selection", {})
        points = selection.get(name, [])
        return [dict(point) for point in points if isinstance(point, dict)]
    except (AttributeError, TypeError):
        return []


def _observation_filter_context() -> dict[str, str]:
    return dict(st.session_state.get("_chr_observation_filters", {}))


def _set_observation_filters(row: dict) -> bool:
    desired = {}
    for field in ("underlying", "surfaced_direction", "right"):
        value = row.get(field)
        if value not in (None, ""):
            desired[field] = str(value)
    if desired == _observation_filter_context():
        return False
    st.session_state["_chr_observation_filters"] = desired
    return True


def _clear_observation_filters() -> None:
    st.session_state["_chr_observation_filters"] = {}


def _filter_observations(frame: pd.DataFrame, filters: dict[str, str]) -> pd.DataFrame:
    filtered = frame.copy()
    for field, value in filters.items():
        if field in filtered.columns:
            filtered = filtered[filtered[field].astype(str) == str(value)]
    return filtered


def _show_observation_filter_strip(filters: dict[str, str]) -> None:
    if not filters:
        st.caption("Click a table row or chart bar to cross-filter this research view.")
        return
    labels = []
    for field, value in filters.items():
        labels.append(f"{_human_column_name(field)}: {value}")
    left, right = st.columns([5, 1])
    left.caption("Active filters · " + " · ".join(labels))
    if right.button("Clear filters", key="clear_observation_filters", width="stretch"):
        _clear_observation_filters()
        st.rerun()


def _show_full_text_details(frame: pd.DataFrame) -> None:
    """Expose values that the compact dataframe can visually truncate."""
    if frame.empty:
        return

    full_text = []
    always_expand = {
        "Admission label",
        "Detail",
        "Notes",
        "Error message",
        "Path",
    }

    for row_index, row in frame.reset_index(drop=True).iterrows():
        for column, value in row.items():
            if value is None:
                continue
            rendered = str(value)
            column_name = str(column)
            if (
                column_name in always_expand
                or "Hash" in column_name
                or len(rendered) >= 40
            ):
                full_text.append((row_index + 1, column_name, rendered))

    if not full_text:
        return

    with st.expander("Full text / identifiers"):
        st.caption(
            "Compact tables may shorten long values visually. "
            "The complete stored values are shown here without abbreviation."
        )
        for row_number, column_name, rendered in full_text[:60]:
            st.markdown(f"**Row {row_number} · {column_name}**")
            st.write(rendered)
        if len(full_text) > 60:
            st.caption(
                f"{len(full_text) - 60} additional long values omitted from this compact detail view."
            )


def _show_table(
    rows,
    *,
    height: int | None = None,
    columns: list[str] | None = None,
) -> None:
    frame = pd.DataFrame(rows)
    if columns:
        available = [name for name in columns if name in frame.columns]
        frame = frame[available]
    frame = _humanize_dataframe(frame)
    dataframe_kwargs = {
        "width": "stretch",
        "hide_index": True,
    }
    if height is not None:
        dataframe_kwargs["height"] = height
    st.dataframe(frame, **dataframe_kwargs)
    _show_full_text_details(frame)


def _show_selectable_table(
    rows,
    *,
    key: str,
    height: int | None = None,
    columns: list[str] | None = None,
):
    """Render a single-row selectable table while preserving source-row order."""
    source = pd.DataFrame(rows).reset_index(drop=True)
    display = source.copy()
    if columns:
        available = [name for name in columns if name in display.columns]
        display = display[available]
    display = _humanize_dataframe(display)
    kwargs = {
        "width": "stretch",
        "hide_index": True,
        "key": key,
        "on_select": "rerun",
        "selection_mode": "single-row",
    }
    if height is not None:
        kwargs["height"] = height
    event = st.dataframe(display, **kwargs)
    _show_full_text_details(display)
    rows_selected = _selection_rows(event)
    if not rows_selected:
        return None
    index = rows_selected[0]
    if index < 0 or index >= len(source):
        return None
    return source.iloc[index].to_dict()


@st.cache_data(show_spinner=False, ttl=300)
def _cached_candidate_model_dossier(candidate: dict) -> dict:
    return run_candidate_model_dossier(candidate, mc_paths=10_000)


st.set_page_config(
    page_title="Christiania",
    page_icon="⚓",
    layout="wide",
    initial_sidebar_state="expanded",
)
inject_christiania_theme()


def _status_label(value) -> str:
    return str(value or "UNKNOWN").replace("_", " ").title()


def _fmt_time(value: str | None) -> str:
    if not value:
        return "—"
    text = str(value)
    if "T" in text:
        return text.split("T", 1)[1][:8]
    return text


def _safe(value, fallback="—"):
    return fallback if value is None else value


def _pct(numerator: int | float, denominator: int | float) -> float:
    if not denominator:
        return 0.0
    return max(0.0, min(float(numerator) / float(denominator), 1.0))


def _html_rows(items: list[tuple[str, str, str | None]]) -> str:
    rows = []
    for label, value, state in items:
        rows.append(
            '<div style="display:flex;justify-content:space-between;gap:.8rem;'
            'padding:.28rem 0;border-bottom:1px solid rgba(255,255,255,.045)">'
            f'<span>{status_dot(state)}{label}</span>'
            f'<strong style="color:#F4F0E7">{value}</strong>'
            '</div>'
        )
    return "".join(rows)


RUNTIME_REFRESH_SECONDS = 180


def _load_runtime_state(*, force: bool = False):
    now = time.monotonic()
    loaded_at = st.session_state.get("_chr_runtime_loaded_at", 0.0)
    stale = (now - loaded_at) >= RUNTIME_REFRESH_SECONDS

    if force or "_chr_snapshot" not in st.session_state or stale:
        with st.spinner("Refreshing Christiania research state…"):
            st.session_state["_chr_snapshot"] = load_command_deck(
                include_provider_health=True
            )
            st.session_state["_chr_backup_inventory"] = inventory_backups().as_dict()
            st.session_state["_chr_runtime_loaded_at"] = now

    return (
        st.session_state["_chr_snapshot"],
        st.session_state["_chr_backup_inventory"],
    )


snapshot, backup_inventory = _load_runtime_state()

with st.sidebar:
    if LOGO_PATH.exists():
        st.image(str(LOGO_PATH), width="stretch")
    st.markdown(
        '<div class="chr-side-caption">NO CRYING IN THE CASINO</div>',
        unsafe_allow_html=True,
    )
    st.divider()

    page = st.radio(
        "Navigation",
        [
            "⚓ Dashboard",
            "🎯 Decision Desk",
            "📜 Research Runs",
            "⚙ Calibration",
            "◉ Observations",
            "⚗ Shadow Lab",
            "∑ Quant Models",
            "🌊 Storm Cellar / 0DTE Lab",
            "⚙ Ops",
        ],
        label_visibility="collapsed",
    )
    page = page.split(" ", 1)[1]

    st.divider()
    if st.button("↻ Refresh deck", width="stretch"):
        _load_runtime_state(force=True)
        st.rerun()

    st.caption(f"Christiania {CHRISTIANIA_VERSION}")

hero()

if not snapshot["ready"]:
    st.error(
        "Christiania cannot open the research deck: "
        f"{snapshot['reason']}"
    )
    st.json(snapshot["database"])
    st.stop()

latest_iteration = snapshot["latest_iteration"]
latest_run = snapshot["latest_run"]
prospective = snapshot["prospective"]
counts = snapshot["research_counts"]
market_clock = snapshot["market_clock"]
daemon_health = snapshot["daemon_health"]
theta_health = snapshot.get("theta_health", {"state": "NOT_PROBED"})
database = snapshot["database"]
readiness = assess_v1_readiness(snapshot, backup_inventory).as_dict()
quality = snapshot.get("data_quality", {})
decision_candidates = snapshot.get("decision_desk_candidates", [])
scientific_decision_enabled = bool(
    any(bool(row.get("decision_enabled")) for row in snapshot.get("models", []))
    and any(bool(row.get("decision_enabled")) for row in snapshot.get("hypotheses", []))
)
calibration_state = calibration_evidence_state(
    models=snapshot.get("models", []),
    hypotheses=snapshot.get("hypotheses", []),
    independent_dates=int(prospective.get("independent_dates", 0)),
)

if page == "Dashboard":
    section_heading("Command overview", "The current operational and research state at a glance.")
    c1, c2, c3, c4 = st.columns(4)

    with c1:
        card(
            "Daemon health",
            _html_rows(
                [
                    ("Research daemon", _status_label(daemon_health.get("state")), daemon_health.get("state")),
                    ("Latest cycle", _status_label(latest_iteration.get("status") if latest_iteration else None), latest_iteration.get("status") if latest_iteration else None),
                    ("Storage & backups", f"{_fmt_count(backup_inventory.get('valid_files', 0))} verified", "READY" if backup_inventory.get("valid_files") else "WARN"),
                ]
            ),
            badge_label="Healthy" if daemon_health.get("state") in {"HEALTHY", "NO_DAEMON_LEASE"} else daemon_health.get("state", "Unknown"),
        )

    with c2:
        card(
            "Theta Terminal",
            _html_rows(
                [
                    ("API readiness", _status_label(theta_health.get("state")), theta_health.get("state")),
                    ("Endpoint", str(theta_health.get("endpoint") or "local /v3"), theta_health.get("state")),
                    ("Latency", _fmt_latency_ms(theta_health.get("latency_ms")), theta_health.get("state")),
                ]
            ),
            badge_label="Operational" if theta_health.get("ready") else _status_label(theta_health.get("state")),
        )

    with c3:
        card(
            "Market clock",
            (
                f'<div style="font-size:2.15rem;font-family:Georgia,serif;color:#F1D08A">{_status_label(market_clock.get("state"))}</div>'
                f'<div style="margin-top:.45rem;color:#9EB4C3">Session date: {_safe((market_clock.get("session") or {}).get("session_date"))}</div>'
                f'<div style="margin-top:.2rem">Next sample: <strong>{_safe(market_clock.get("next_sample_at"))}</strong></div>'
            ),
            badge_label="XNYS",
            badge_tone="info",
        )

    with c4:
        card(
            "Latest Research Run",
            _html_rows(
                [
                    ("Run", str(latest_run.get("id") if latest_run else "—"), latest_run.get("status") if latest_run else None),
                    ("Status", _status_label(latest_run.get("status") if latest_run else None), latest_run.get("status") if latest_run else None),
                    ("Succeeded", _fmt_count(latest_run.get("succeeded_underlyings", 0) if latest_run else 0), "SUCCESS"),
                    ("Failed", _fmt_count(latest_run.get("failed_underlyings", 0) if latest_run else 0), "FAIL" if latest_run and latest_run.get("failed_underlyings") else "SUCCESS"),
                ]
            ),
            badge_label="Latest",
            badge_tone="info",
        )

    section_heading("Research pulse", "Prospective evidence grows independently from product readiness.")
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Prospective dates", _fmt_count(prospective["independent_dates"]), "first review at 5")
    m2.metric("Observation rows", _fmt_count(prospective["observation_rows"]))
    m3.metric("Surfaced observations", _fmt_count(counts["surfaced_total"]))
    m4.metric("Shadow candidates", _fmt_count(counts["shadow_candidates"]))
    m5.metric("Recovered samples", _fmt_count(prospective["recovered_samples"]), "provenance retained")
    _visual_note(
        "How much evidence Christiania has collected. Prospective dates matter more than raw row count: "
        "many observations from one day are still only one independent market date."
    )

    chart_left, chart_right = st.columns([1, 1.35])
    with chart_left:
        section_heading("Recent daemon activity")
        recent = snapshot.get("recent_iterations", [])
        if recent:
            df = pd.DataFrame(recent[::-1])
            df["cycle"] = range(1, len(df) + 1)
            chart_df = df.set_index("cycle")[["proposals_count", "blocked_count", "outcome_mark_count"]].fillna(0)
            st.line_chart(chart_df, height=275)
            chart_note(
                "Shows proposal, block and shadow-mark counts across the most recent daemon cycles; "
                "it is operational activity, not performance."
            )
        else:
            st.info("No daemon iterations recorded.")

    with chart_right:
        section_heading("Recent research runs")
        rows = snapshot.get("recent_iterations", [])[:10]
        if rows:
            table = pd.DataFrame(rows)[
                ["id", "scheduled_for", "status", "research_run_id", "proposals_count", "blocked_count", "outcome_mark_count", "error_type"]
            ]
            _show_table(table, height=275)
            _visual_note(
                "One row is one daemon cycle: when it ran, whether it completed, and how many proposals, "
                "blocks and shadow follow-up marks that cycle produced."
            )
        else:
            st.info("No research runs recorded.")

    lower1, lower2, lower3 = st.columns([1.1, 1.1, 0.8])
    with lower1:
        section_heading("Calibration evidence state")
        dates = readiness["independent_prospective_dates"]
        st.progress(_pct(dates, 20), text=f"{dates}/20 prospective dates toward preregistration review")
        st.markdown(
            f"**Calibration:** {badge(calibration_state['state'], tone=calibration_state['tone'])}",
            unsafe_allow_html=True,
        )
        st.caption(calibration_state["detail"])
        st.markdown(
            f"**Product state:** {badge(_status_label(readiness['product_state']))}",
            unsafe_allow_html=True,
        )
        st.markdown(
            f"**Scientific maturity:** {badge(_status_label(readiness['scientific_state']), tone='info')}",
            unsafe_allow_html=True,
        )

    with lower2:
        section_heading("Quant model governance")
        registry = quant_model_catalog()
        enabled = sum(1 for row in registry if row.get("decision_enabled"))
        st.metric("Registered models", _fmt_count(len(registry)), f"{_fmt_count(enabled)} decision-enabled")
        st.caption("Models are maps, not territory. All V1 challengers remain research-only.")

    with lower3:
        section_heading("Verified backups")
        latest_age = backup_inventory.get("latest_valid_age_hours")
        st.metric(
            "Valid backups",
            _fmt_count(backup_inventory.get("valid_files", 0)),
            "—" if latest_age is None else f"latest {_fmt_number(latest_age, decimals=1)}h ago",
        )
        if backup_inventory.get("invalid_files"):
            st.error(f"{backup_inventory['invalid_files']} invalid backup(s)")
        else:
            st.success("Recovery inventory nominal")

elif page == "Decision Desk":
    section_heading(
        "Decision Desk V2",
        "One candidate-level synthesis of anomaly evidence, exact structure, settlement, market quality, risk, prospective history, shadow follow-up, model diagnostics and scenario stress.",
    )
    st.caption(
        "CURRENT GLOBAL CONCLUSION: NO TRADE while candidate-specific scientific governance remains disabled. "
        "The desk can also classify research as CONTINUE SHADOW. ELIGIBLE FOR MANUAL REVIEW requires every gate. "
        "Christiania does not submit orders."
    )

    universe_state = cash_settled_research_universe()
    u1, u2, u3 = st.columns(3)
    u1.metric("Cash-settled research universe", ", ".join(universe_state.symbols))
    u2.metric("Provider compatibility", universe_state.provider_compatibility_state)
    u3.metric("Live collection enabled", "YES" if universe_state.live_collection_enabled else "NO")
    _visual_note(universe_state.note)

    with st.expander("Session risk controls", expanded=True):
        st.caption(
            "These are manual review controls for this session. They do not create broker orders. A zero value blocks manual eligibility. "
            "Defined-risk maximum loss is primary; the loss threshold is only a monitoring trigger."
        )
        rc1, rc2, rc3 = st.columns(3)
        max_trade_risk_eur = rc1.number_input(
            "Maximum loss budget per trade (€)", min_value=0.0, max_value=500.0,
            value=float(st.session_state.get("_chr_max_trade_risk_eur", 0.0)), step=5.0,
            key="decision_max_trade_risk_eur",
        )
        stop_loss_pct = rc2.number_input(
            "Planned loss threshold (% of reserved risk)", min_value=0.0, max_value=100.0,
            value=float(st.session_state.get("_chr_stop_loss_pct", 0.0)), step=5.0,
            key="decision_stop_loss_pct",
        )
        rc3.metric("Active bankroll cap", "€500", "no compounding")
        st.session_state["_chr_max_trade_risk_eur"] = max_trade_risk_eur
        st.session_state["_chr_stop_loss_pct"] = stop_loss_pct
        st.caption("A stop threshold is a monitoring rule, not a guaranteed fill. Defined-risk maximum loss remains the primary protection.")

    board = build_candidate_review_board(
        decision_candidates,
        models=snapshot.get("models", []),
        hypotheses=snapshot.get("hypotheses", []),
        max_trade_risk_eur=max_trade_risk_eur if max_trade_risk_eur > 0 else None,
        stop_loss_fraction=(stop_loss_pct / 100.0) if stop_loss_pct > 0 else None,
    )

    no_trade_count = sum(1 for row in board if row.get("decision_desk_disposition") == "NO TRADE")
    shadow_count = sum(1 for row in board if row.get("decision_desk_disposition") == "CONTINUE SHADOW")
    eligible_count = sum(1 for row in board if row.get("decision_desk_disposition") == "ELIGIBLE FOR MANUAL REVIEW")
    cash_verified_count = sum(1 for row in board if row.get("settlement_state") == "VERIFIED_CASH_SETTLED")
    top1, top2, top3, top4 = st.columns(4)
    top1.metric("Tracked candidates", _fmt_count(len(board)))
    top2.metric("NO TRADE", _fmt_count(no_trade_count))
    top3.metric("Continue shadow", _fmt_count(shadow_count))
    top4.metric("Manual-review eligible", _fmt_count(eligible_count), "0 is valid")
    st.metric("Cash-settlement verified", _fmt_count(cash_verified_count), "exact contract identity required")
    _visual_note(
        "The desk separates hard safety failure from scientific incompleteness. NO TRADE means a hard gate failed; CONTINUE SHADOW means the candidate may remain useful research but has not earned manual-trade review."
    )

    if cash_verified_count == 0 and board:
        st.warning(
            "No tracked candidate currently passes the exact cash-settlement gate. Existing equity/ETF candidates remain useful shadow research, but Christiania will not recommend them for live/manual use."
        )

    if not board:
        st.info("No shadow candidates are available for Decision Desk synthesis yet.")
    else:
        section_heading("Research review board", "Select a row to open the complete candidate dossier.")
        board_columns = [
            "research_rank", "candidate_id", "underlying", "structure_id", "anomaly_direction",
            "abs_iv_residual", "settlement_state", "market_quality_state", "candidate_governance_state",
            "prospective_evidence_state", "time_to_expiry_state", "decision_blocker_count",
            "decision_desk_disposition", "research_action",
        ]
        selected = _show_selectable_table(board, key="decision_desk_review_board_v2", columns=board_columns, height=340)
        _visual_note(
            "Research rank is only an inspection priority. It is not probability of profit, calibrated EV, or a recommendation score."
        )
        if selected is None:
            selected = board[0]
            st.caption("No row selected — showing the highest research-review priority candidate.")
        candidate_id = int(selected.get("candidate_id"))
        full_selected = next((row for row in board if int(row.get("candidate_id")) == candidate_id), selected)

        settlement = classify_settlement(
            full_selected.get("underlying"), observed_exercise_style=full_selected.get("exercise_style"),
            reference_contract_id=full_selected.get("reference_contract_id"), shares_per_contract=full_selected.get("target_shares_per_contract"),
        )
        risk_plan = build_risk_plan(
            full_selected, max_trade_risk_eur=max_trade_risk_eur if max_trade_risk_eur > 0 else None,
            stop_loss_fraction=(stop_loss_pct / 100.0) if stop_loss_pct > 0 else None,
        )
        governance = resolve_candidate_governance(full_selected, models=snapshot.get("models", []), hypotheses=snapshot.get("hypotheses", []))
        market_quality = assess_market_quality(full_selected)
        evidence = assess_prospective_evidence(full_selected)
        tte = resolve_time_to_expiry(full_selected)
        exit_monitor = assess_exit_monitor(full_selected, risk_plan)

        section_heading("Frozen shadow risk evidence")
        frozen_risk = full_selected.get("frozen_risk_plan")
        if not frozen_risk:
            st.warning("NOT FROZEN — session controls are exploratory and do not count as prospective risk evidence.")
            st.caption("Freeze a plan with record_shadow_risk_plan_v1.py before using risk-management outcomes as prospective evidence.")
        else:
            fr1, fr2, fr3, fr4 = st.columns(4)
            fr1.metric("Risk-plan state", "FROZEN")
            fr2.metric("Defined max loss", f"€{float(frozen_risk.get('max_defined_loss_eur_minor') or 0)/100:.2f}")
            fr3.metric("Reserved risk", f"€{float(frozen_risk.get('reserved_risk_eur_minor') or 0)/100:.2f}")
            fr4.metric("Latest monitor", str(frozen_risk.get("overall_state") or "NOT ASSESSED"))
            st.caption("Frozen plans are immutable. Assessments are append-only. A stop threshold is never presented as a guaranteed fill.")

        section_heading("Current conclusion")
        disposition = full_selected.get("decision_desk_disposition")
        blockers = list(full_selected.get("decision_blockers") or [])
        if disposition == "NO TRADE":
            st.error("NO TRADE")
        elif disposition == "CONTINUE SHADOW":
            st.warning("CONTINUE SHADOW — useful research, not eligible for manual trade review")
        else:
            st.success("ELIGIBLE FOR MANUAL REVIEW — still not an order")
        if blockers:
            st.markdown("**Unresolved / blocking reasons:** " + " · ".join(blockers))
        st.caption("A visually attractive anomaly can never override settlement, quote quality, evidence, governance or risk controls.")

        section_heading("Candidate dossier", "What Christiania observed at inception and what happened afterward.")
        d1, d2, d3, d4 = st.columns(4)
        d1.metric("Underlying", str(full_selected.get("underlying") or "—"))
        d2.metric("Structure", str(full_selected.get("structure_id") or "—"))
        d3.metric("Absolute IV residual", _fmt_number(full_selected.get("abs_iv_residual"), decimals=4))
        latest_pnl = full_selected.get("latest_estimated_net_pnl_eur_minor")
        d4.metric("Latest shadow net P&L", "—" if latest_pnl is None else f"€{_fmt_number(float(latest_pnl)/100.0, decimals=2)}")
        _show_table([full_selected], columns=[
            "candidate_id", "research_run_id", "surfaced_at", "underlying", "expiration", "right", "target_strike",
            "hypothesis_family", "hypothesis_version", "scanner_family_id", "scanner_version", "primary_research_model",
            "anomaly_direction", "iv_residual", "abs_iv_residual", "residual_threshold", "admission_decision",
            "admission_reason_code", "admission_label", "collection_status", "retry_count", "was_recovered",
            "mark_count", "validated_outcomes", "latest_mark_at",
        ])

        section_heading("Exact hypothetical structure")
        legs = full_selected.get("structure_legs") or []
        if legs:
            _show_table(legs, columns=[
                "side", "quantity", "right", "strike", "entry_price", "bid", "ask", "quote_at",
                "implied_volatility", "delta", "gamma", "theta", "vega", "shares_per_contract", "option_quote_id",
            ])
            _visual_note("These are persisted inception legs and prices, not a fresh executable quote.")
        else:
            st.warning("Persisted structure legs could not be reconstructed.")

        g1, g2, g3 = st.columns(3)
        with g1:
            section_heading("Settlement & contract gate")
            st.metric("Settlement", settlement.settlement_type)
            st.metric("Exercise style", settlement.exercise_style)
            st.metric("Contract identity", settlement.contract_identity_state)
            st.metric("Multiplier", settlement.multiplier_state)
            (st.success if settlement.live_eligible else st.error)(settlement.reason)
            st.caption(f"Policy provenance: {settlement.provenance}")
        with g2:
            section_heading("Market quality")
            st.metric("State", market_quality.state)
            st.metric("Quote age", "—" if market_quality.quote_age_seconds is None else f"{_fmt_number(market_quality.quote_age_seconds, decimals=1)} s")
            st.metric("Spread / mid", "—" if market_quality.spread_to_mid is None else f"{_fmt_number(market_quality.spread_to_mid*100.0, decimals=2)}%")
            if market_quality.blockers:
                st.error(" · ".join(market_quality.blockers))
            if market_quality.warnings:
                st.warning(" · ".join(market_quality.warnings))
            _visual_note("Manual eligibility requires a fresh quote and bounded spread. Historical inception quotes cannot masquerade as executable prices.")
        with g3:
            section_heading("Risk & loss monitor")
            st.metric("Reserved defined risk", "—" if risk_plan.reserved_risk_eur is None else f"€{_fmt_number(risk_plan.reserved_risk_eur, decimals=2)}")
            st.metric("Planned loss threshold", "NOT CONFIGURED" if risk_plan.planned_loss_trigger_eur is None else f"−€{_fmt_number(risk_plan.planned_loss_trigger_eur, decimals=2)}")
            st.metric("Bankroll exposure", "—" if risk_plan.bankroll_fraction is None else f"{_fmt_number(risk_plan.bankroll_fraction*100.0, decimals=1)}%")
            st.metric("Shadow loss monitor", exit_monitor["loss_threshold_state"])
            st.caption(risk_plan.note)

        section_heading("Candidate-specific scientific governance")
        gv1, gv2, gv3 = st.columns(3)
        gv1.metric("Primary frozen model", governance.primary_model or "UNRESOLVED")
        gv2.metric("Decision permission", "ENABLED" if governance.decision_enabled else "DISABLED")
        gv3.metric("TTE semantics", tte["state"])
        if governance.blockers:
            st.warning(" · ".join(governance.blockers))
        _visual_note(governance.note + " " + tte["note"])

        section_heading("Prospective evidence from similar candidates")
        e1, e2, e3, e4 = st.columns(4)
        e1.metric("Independent dates", _fmt_count(evidence.independent_dates))
        e2.metric("Similar candidates", _fmt_count(evidence.candidate_count))
        e3.metric("Validated outcomes", _fmt_count(evidence.validated_outcomes))
        e4.metric("Mean validated net P&L", "—" if evidence.mean_net_pnl_eur is None else f"€{_fmt_number(evidence.mean_net_pnl_eur, decimals=2)}")
        st.warning(evidence.state)
        _visual_note(evidence.note)

        section_heading("Full model dossier", "Benchmark diagnostics are separated from uncalibrated stress models.")
        if not full_selected.get("model_input_complete"):
            st.warning("Full model dossier unavailable because persisted model inputs are incomplete. Christiania will not invent defaults.")
        else:
            with st.spinner("Running cached multi-model diagnostics…"):
                dossier = _cached_candidate_model_dossier(full_selected)
            if dossier.get("state") != "RESEARCH_ONLY":
                st.warning(dossier.get("reason") or dossier.get("state"))
            else:
                st.warning(dossier["reason"])
                model_rows = dossier.get("structure_models", [])
                if model_rows:
                    _show_table(model_rows)
                    model_df = pd.DataFrame(model_rows).set_index("model")[["fair_value_per_contract"]]
                    st.bar_chart(model_df, height=320)
                    _visual_note("Benchmark bars are diagnostic cross-checks. Heston and Merton are stress models here and do not participate in a headline fair-value vote.")
                q1, q2, q3 = st.columns(3)
                q1.metric("Benchmark center / share", _fmt_number(dossier.get("benchmark_center_per_share"), decimals=4))
                q2.metric("Benchmark range / share", _fmt_number(dossier.get("benchmark_range_per_share"), decimals=4))
                q3.metric("Expected value", "NOT CALIBRATED", "decision use disabled")

                section_heading("Scenario stress")
                scenario = dossier.get("scenarios", {})
                if scenario.get("rows"):
                    _show_table(scenario["rows"])
                _visual_note(scenario.get("reason") or "No scenario output available.")

                section_heading("Structure Greeks")
                _show_table([dossier.get("structure_greeks_per_contract", {})])
                _visual_note("Greeks describe sensitivities, not which market move will happen.")

        section_heading("Arguments for / against")
        positives = []
        negatives = []
        if full_selected.get("admission_decision") == "ADMITTED":
            positives.append("Passed the existing shadow-admission process.")
        if settlement.live_eligible:
            positives.append("Exact persisted contract passes the cash-settlement gate.")
        if market_quality.liquidity_pass:
            positives.append("Observed bid/ask spread passes the current liquidity threshold.")
        if evidence.validated_outcomes:
            positives.append(f"There are {evidence.validated_outcomes} validated outcomes in the similar-candidate evidence pool.")
        negatives.extend(blockers)
        a1, a2 = st.columns(2)
        with a1:
            st.markdown("**For further research**")
            st.markdown("\n".join(f"- {item}" for item in positives) if positives else "- No positive evidence claim is strong enough to highlight yet.")
        with a2:
            st.markdown("**Against manual trading**")
            st.markdown("\n".join(f"- {item}" for item in negatives) if negatives else "- No unresolved blocker recorded.")

        st.info(
            "Net calibrated EV is intentionally not fabricated. Event/jump calendar context and exact expiration timestamps are still explicit missing-data gates. "
            "Until those are real and candidate-specific prospective governance is enabled, Christiania cannot promote a candidate to manual-trade review."
        )

elif page == "Research Runs":
    section_heading("Research runs", "Collection cadence, provider outcomes, proposals and marks.")
    selected_run = None
    if snapshot.get("recent_iterations"):
        selected_run = _show_selectable_table(
            snapshot["recent_iterations"],
            key="research_runs_selectable",
        )
        _visual_note(
            "One row is one scheduled research cycle. Select a row to focus the run-specific diagnostics below; "
            "selection changes only the view, never the stored research state."
        )
    else:
        st.info("No daemon iterations recorded.")

    if selected_run:
        st.caption(
            f"Selected cycle {_fmt_count(selected_run.get('id'))} · research run "
            f"{_safe(selected_run.get('research_run_id'))} · {_status_label(selected_run.get('status'))}"
        )

    c1, c2 = st.columns(2)
    with c1:
        section_heading("Session summary")
        st.json(snapshot.get("session", {}))
    with c2:
        section_heading("Data-quality pulse")
        st.json(quality.get("iteration_window", {}))

    if quality.get("recent_failed_underlyings"):
        section_heading("Recent failed underlying samples", "Failure reasons remain explicit and queryable.")
        failed_rows = quality["recent_failed_underlyings"]
        if selected_run and selected_run.get("research_run_id") is not None:
            run_id = selected_run.get("research_run_id")
            narrowed = [row for row in failed_rows if row.get("run_id") == run_id]
            if narrowed:
                failed_rows = narrowed
                st.caption(f"Filtered to research run {run_id} from the selected cycle.")
        _show_table(failed_rows)
        _visual_note(
            "These are individual underlying collections that failed. They stay visible so a completed cycle cannot "
            "silently look cleaner than the data it actually collected."
        )

elif page == "Calibration":
    section_heading("Calibration", "Evidence accumulation and frozen prospective governance.")
    if calibration_state["tone"] == "bad":
        st.error(calibration_state["state"] + " — " + calibration_state["detail"])
    else:
        st.warning(calibration_state["state"] + " — " + calibration_state["detail"])
    st.caption(
        "Calibration status is scientific evidence maturity, not trading readiness. "
        "Decision and admission flags remain authoritative."
    )
    c1, c2, c3 = st.columns(3)
    c1.metric("Independent dates", _fmt_count(prospective["independent_dates"]), "first descriptive review at 5")
    c2.metric("Prospective rows", _fmt_count(prospective["observation_rows"]))
    c3.metric("Recovered samples", _fmt_count(prospective["recovered_samples"]), "visible covariate")
    _visual_note(
        "This is evidence maturity, not a trading score. Independent dates are the main clock because repeated rows "
        "inside one market day are not independent new days."
    )

    st.progress(_pct(prospective["independent_dates"], 20), text=f"{prospective['independent_dates']}/20 dates toward preregistration review")

    section_heading("Frozen hypotheses")
    _show_table(snapshot.get("hypotheses", []))
    st.caption(
        "Friendly names are reviewed aliases only. The exact backend hypothesis ID is shown alongside every alias."
    )

    section_heading("Research model registry")
    _show_table(snapshot.get("models", []))
    st.caption(
        "Friendly model names never replace versioned backend IDs; unknown identifiers are displayed verbatim."
    )

elif page == "Observations":
    section_heading("Surfaced observations", "OBSERVATIONAL ONLY — not validated edge and not trade signals. No broker-order path.")
    if snapshot.get("recent_anomalies"):
        source_df = pd.DataFrame(snapshot["recent_anomalies"]).reset_index(drop=True)
        source_df["observation_row"] = source_df.index.astype(int)
        filters = _observation_filter_context()
        _show_observation_filter_strip(filters)
        filtered_df = _filter_observations(source_df, filters).reset_index(drop=True)

        table_pick = _show_selectable_table(
            filtered_df.drop(columns=["observation_row"], errors="ignore"),
            key="observations_selectable_table",
        )
        if table_pick and _set_observation_filters(table_pick):
            st.rerun()
        _visual_note(
            "Each row is an anomaly Christiania surfaced for investigation. Click a row to cross-filter this page. "
            "A surfaced observation is a question to investigate, not a recommendation to trade."
        )

        if "abs_iv_residual" in filtered_df.columns and not filtered_df.empty:
            chart_df = filtered_df.head(25).copy()
            chart_df["abs_iv_residual"] = pd.to_numeric(
                chart_df["abs_iv_residual"], errors="coerce"
            )
            chart_df = chart_df.dropna(subset=["abs_iv_residual"])
            if not chart_df.empty:
                spec = {
                    "mark": {"type": "bar", "tooltip": True},
                    "params": [
                        {
                            "name": "observation_pick",
                            "select": {
                                "type": "point",
                                "fields": ["observation_row", "underlying", "surfaced_direction", "right"],
                                "on": "click",
                                "clear": False,
                            },
                        }
                    ],
                    "encoding": {
                        "x": {
                            "field": "underlying",
                            "type": "nominal",
                            "title": "Underlying",
                            "sort": None,
                        },
                        "y": {
                            "field": "abs_iv_residual",
                            "type": "quantitative",
                            "title": "Absolute IV residual",
                        },
                        "opacity": {
                            "condition": {"param": "observation_pick", "value": 1.0},
                            "value": 0.45,
                        },
                        "tooltip": [
                            {"field": "underlying", "type": "nominal", "title": "Underlying"},
                            {"field": "expiration", "type": "nominal", "title": "Expiration"},
                            {"field": "strike", "type": "quantitative", "title": "Strike"},
                            {"field": "right", "type": "nominal", "title": "Right"},
                            {"field": "abs_iv_residual", "type": "quantitative", "title": "Absolute IV residual"},
                            {"field": "surfaced_direction", "type": "nominal", "title": "Direction"},
                        ],
                    },
                }
                chart_event = st.vega_lite_chart(
                    chart_df,
                    spec,
                    width="stretch",
                    height=280,
                    key="observations_residual_chart",
                    on_select="rerun",
                    selection_mode="observation_pick",
                )
                selected_points = _vega_selected_points(chart_event, "observation_pick")
                if selected_points:
                    point = selected_points[0]
                    row_id = point.get("observation_row")
                    if row_id is not None:
                        matches = source_df[source_df["observation_row"] == int(row_id)]
                        if not matches.empty and _set_observation_filters(matches.iloc[0].to_dict()):
                            st.rerun()
                _visual_note(
                    "Shows how far observed IV differs from the local model. Larger bars mean more disagreement, "
                    "not stronger trade conviction. Click a bar to cross-filter the table and chart; use Clear filters to restore the full view."
                )
        st.caption(
            f"Showing {_fmt_count(len(filtered_df))} of {_fmt_count(len(source_df))} recent surfaced observations."
        )
    else:
        st.info("No surfaced observations recorded.")

elif page == "Shadow Lab":
    section_heading(
        "Shadow Lab",
        "Candidate follow-up: inception, subsequent marks, validated outcomes, and current evidence state.",
    )
    tracking = snapshot.get("shadow_tracking", {})
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Proposals", _fmt_count(counts["proposals_total"]), f"{_fmt_count(counts['proposals_blocked'])} builder-blocked")
    c2.metric("Admitted shadows", _fmt_count(counts["admitted_total"]), f"{_fmt_count(counts['admission_blocked'])} blocked")
    c3.metric("Recorded marks", _fmt_count(counts["shadow_marks"]), f"{_fmt_count(tracking.get('marked_candidates', 0))} candidate(s)")
    c4.metric("Validated hold/mark outcomes", _fmt_count(tracking.get("validated_outcomes", 0)), "raw population")
    c5.metric("Predeclared risk exits", _fmt_count(tracking.get("risk_exit_outcomes", 0)), f"{_fmt_count(tracking.get('eligible_risk_exit_outcomes', 0))} evidence-eligible")
    _visual_note(
        "This is the follow-up laboratory: proposals are ideas, admitted shadows are hypothetical experiments we track, "
        "marks are later valuations. Validated hold/mark outcomes and predeclared risk-trigger exits are deliberately separate measurement populations."
    )

    followup = snapshot.get("shadow_candidate_followup", [])
    if followup:
        choices = {
            f"#{row['candidate_id']} · {row['underlying']} · {hypothesis_label(row.get('hypothesis_family'))}": row
            for row in followup
        }
        selected_label = st.selectbox(
            "Shadow candidate",
            list(choices),
            key="shadow_candidate_selector",
        )
        selected = choices[selected_label]
        candidate_id = int(selected["candidate_id"])

        section_heading("Candidate lifecycle")
        a, b, c, d = st.columns(4)
        a.metric("Underlying", selected.get("underlying") or "—")
        b.metric("Current state", _status_label(selected.get("current_state")))
        c.metric("Thesis assessment", selected.get("thesis_assessment") or "NOT YET SCORED")
        d.metric("Validated trade result", selected.get("validated_trade_result") or "NOT YET VALIDATED")
        _visual_note(
            "Thesis assessment asks whether the original market idea was right. Validated trade result asks whether the "
            "hypothetical structure made money after the allowed outcome rules. Those are deliberately different questions."
        )

        details = pd.DataFrame([selected])
        _show_table(
            details.to_dict("records"),
            columns=[
                "candidate_id",
                "underlying",
                "surfaced_at",
                "hypothesis_family",
                "hypothesis_version",
                "scanner_family_id",
                "scanner_version",
                "structure_id",
                "anomaly_direction",
                "admission_label",
                "current_state",
                "mark_count",
                "validated_outcomes",
                "latest_mark_at",
                "latest_estimated_net_pnl_eur_minor",
                "validated_net_pnl_eur_minor",
                "thesis_assessment",
                "validated_trade_result",
            ],
        )

        candidate_marks = [
            row for row in snapshot.get("shadow_mark_history", [])
            if int(row.get("candidate_id")) == candidate_id
        ]
        if candidate_marks:
            marks = pd.DataFrame(candidate_marks)
            marks["Observed"] = pd.to_datetime(marks["observed_at"], errors="coerce")
            marks["Estimated net P&L (€)"] = (
                pd.to_numeric(marks["estimated_net_pnl_eur_minor"], errors="coerce") / 100.0
            )
            plot = marks.dropna(subset=["Observed", "Estimated net P&L (€)"]).set_index("Observed")[["Estimated net P&L (€)"]].sort_index()
            if not plot.empty:
                st.line_chart(plot, height=300)
                chart_note(
                    "Recorded estimated net EUR P&L for this candidate through time. "
                    "Only outcome-eligible marks count as validated trade outcomes; stress marks remain diagnostics."
                )
            _show_table(
                candidate_marks,
                columns=[
                    "observed_at",
                    "provider",
                    "estimated_net_pnl_eur_minor",
                    "quality_state",
                    "measurement_role",
                    "outcome_eligible",
                ],
            )
        else:
            st.info("This candidate has no follow-up marks yet.")

        st.caption(
            "Thesis assessment and validated trade profitability are deliberately separate. "
            "Christiania does not infer thesis correctness from a profitable mark. "
            "Historical non-outcome marks remain independent-leg liquidation stress marks."
        )

        section_heading("All candidate follow-up")
        _show_table(
            followup,
            columns=[
                "candidate_id",
                "underlying",
                "hypothesis_family",
                "current_state",
                "mark_count",
                "validated_outcomes",
                "thesis_assessment",
                "validated_trade_result",
                "latest_mark_at",
            ],
        )
    else:
        st.info("No admitted shadow candidate has follow-up data yet.")

    section_heading("Recent structure proposals")
    if snapshot.get("recent_proposals"):
        _show_table(snapshot["recent_proposals"])
    else:
        st.info("No structure proposals recorded.")

    section_heading("Recent shadow candidates")
    if snapshot.get("recent_candidates"):
        _show_table(snapshot["recent_candidates"])
    else:
        st.info("No shadow candidates recorded.")

elif page == "Quant Models":
    section_heading("Quantitative model bench", "Measure. Understand. Disagree constructively.")
    st.caption(
        "RESEARCH ONLY — challenger-model disagreement, calibration and scenario diagnostics. "
        "No model on this page can admit a candidate or submit an order."
    )

    _show_table(quant_model_catalog())
    _visual_note(
        "These are research tools that can price and disagree. A model appearing here does not give it permission to admit a candidate or make a trading decision."
    )

    with st.form("quant-vanilla-bench"):
        c1, c2, c3, c4 = st.columns(4)
        spot = c1.number_input("Spot", min_value=0.01, value=100.0, step=1.0)
        strike = c2.number_input("Strike", min_value=0.01, value=100.0, step=1.0)
        days = c3.number_input("Days to expiry", min_value=1, value=30, step=1)
        right = c4.selectbox("Right", ["CALL", "PUT"])
        c1, c2, c3, c4 = st.columns(4)
        vol_pct = c1.number_input("Volatility %", min_value=0.01, value=25.0, step=1.0)
        rate_pct = c2.number_input("Rate %", value=3.0, step=0.25)
        div_pct = c3.number_input("Dividend yield %", value=0.0, step=0.25)
        market_price = c4.number_input("Market price (optional)", min_value=0.0, value=0.0, step=0.1)
        submitted = st.form_submit_button("Run research bench")

    if submitted:
        try:
            option = VanillaOption(
                spot=float(spot),
                strike=float(strike),
                time_to_expiry=float(days) / 365.0,
                rate=float(rate_pct) / 100.0,
                volatility=float(vol_pct) / 100.0,
                right=right,
                dividend_yield=float(div_pct) / 100.0,
            )
            result = run_vanilla_bench(
                option,
                market_price=None if market_price <= 0 else float(market_price),
                mc_paths=50_000,
            ).as_dict()
        except QuantInputError as exc:
            st.error(str(exc))
        else:
            st.warning(result["governance"]["warning"])
            prices = pd.DataFrame(
                [{"model": name, "price": value} for name, value in result["model_prices"].items()]
            ).set_index("model")
            left, right_col = st.columns([1.15, 0.85])
            with left:
                st.bar_chart(prices, height=330)
                chart_note(
                    "Compares research-only model prices for the same option inputs. "
                    "Dispersion is a diagnostic of model disagreement, not a trading signal."
                )
            with right_col:
                disagreement = result["disagreement"]
                st.metric("Model range", _fmt_number(disagreement["absolute_range"], decimals=4))
                st.metric("Consensus mean", _fmt_number(disagreement["mean"], decimals=4))
                st.metric(
                    "Market − consensus",
                    "—" if disagreement["market_minus_consensus"] is None else _fmt_number(disagreement["market_minus_consensus"], decimals=4),
                )
            section_heading("Analytic Greeks")
            _show_table([result["greeks"]])
            with st.expander("Model diagnostics"):
                st.json(
                    {
                        "implied_volatility": result["implied_volatility"],
                        "monte_carlo": result["monte_carlo"],
                        "heston_parameters": result["heston_parameters"],
                        "merton_parameters": result["merton_parameters"],
                    }
                )

elif page == "Storm Cellar / 0DTE Lab":
    st.markdown(
        """
        <div class="chr-casino">
          <h3>🌊 Storm Cellar / 0DTE Lab — EXPERIMENTAL, SEPARATE</h3>
          <p><strong>Speculative by charter, quantitative by discipline.</strong> Tiny capped risk, defined-risk structures, explicit slippage, jump/event risk, gamma exposure and scenario EV.</p>
          <p><strong>NOT PART OF CORE ENGINE.</strong> No automatic promotion into the main research engine. The lab must be able to say NO TRADE.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    c1, c2, c3 = st.columns(3)
    c1.metric("Governance", "ISOLATED", "research-only")
    c2.metric("Risk stance", "TINY / CAPPED", "defined risk")
    c3.metric("Decision state", "DISABLED", "NO TRADE allowed")
    section_heading("V1 lab charter")
    st.markdown(
        "- Intraday implied-vs-realized volatility\n"
        "- Gamma exposure and convexity\n"
        "- Jump and scheduled-event risk\n"
        "- Transaction costs and slippage\n"
        "- Probability-weighted scenario EV\n"
        "- Calibration and falsification\n"
        "- Explicit NO TRADE output"
    )

elif page == "Ops":
    section_heading(
        "Operations",
        "Deployment, scientific/product readiness and runtime diagnostics in one operator surface.",
    )
    ops_view = st.radio(
        "Ops view",
        ["Readiness", "Release", "System"],
        horizontal=True,
        label_visibility="collapsed",
        key="ops_view",
    )

    if ops_view == "Readiness":
        section_heading(
            "V1 readiness",
            "Operational readiness is deliberately separate from scientific maturity.",
        )
        c1, c2, c3 = st.columns(3)
        c1.metric("Product state", _status_label(readiness["product_state"]))
        c2.metric(
            "Scientific state",
            _status_label(readiness["scientific_state"]),
            f"{_fmt_count(readiness['independent_prospective_dates'])} prospective date(s)",
        )
        c3.metric(
            "Latest verified backup",
            "None"
            if backup_inventory["latest_valid_age_hours"] is None
            else f"{_fmt_number(backup_inventory['latest_valid_age_hours'], decimals=1)}h ago",
            f"{_fmt_count(backup_inventory['valid_files'])} valid / {_fmt_count(backup_inventory['invalid_files'])} invalid",
        )

        _show_table(readiness["checks"])
        _visual_note(
            "This is the pre-flight checklist for the product. Passing operational checks does not promote the science or enable trading decisions."
        )

        section_heading("Data-quality pulse")
        iterations = quality.get("iteration_window", {})
        underlyings = quality.get("underlying_totals", {})
        failed_or_orphaned = int(iterations.get("failed", 0)) + int(iterations.get("orphaned", 0))
        underlying_failures = int(underlyings.get("failed", 0) or 0)

        q1, q2, q3, q4 = st.columns(4)
        with q1:
            card(
                "Recent completed",
                f'<div style="font-size:2rem;font-family:Georgia,serif;color:#F1D08A">{_fmt_count(iterations.get('completed', 0))}</div>',
                badge_label="Operational",
                badge_tone="info",
            )
        with q2:
            card(
                "Failed / orphaned",
                f'<div style="font-size:2rem;font-family:Georgia,serif;color:#F0B36A">{_fmt_count(failed_or_orphaned)}</div>'
                '<div style="margin-top:.35rem;color:#C6D2D9">Recent daemon iterations requiring review.</div>',
                badge_label="Review" if failed_or_orphaned else "None",
                badge_tone="warn" if failed_or_orphaned else "good",
            )
        with q3:
            card(
                "Underlying failures",
                f'<div style="font-size:2rem;font-family:Georgia,serif;color:#F0B36A">{_fmt_count(underlying_failures)}</div>'
                '<div style="margin-top:.35rem;color:#C6D2D9">Failed underlying collections in the quality window.</div>',
                badge_label="Review" if underlying_failures else "None",
                badge_tone="warn" if underlying_failures else "good",
            )
        with q4:
            card(
                "Recovered underlyings",
                f'<div style="font-size:2rem;font-family:Georgia,serif;color:#F1D08A">{_fmt_count(underlyings.get('recovered', 0))}</div>'
                '<div style="margin-top:.35rem;color:#C6D2D9">Recovery provenance remains retained.</div>',
                badge_label="Provenance",
                badge_tone="info",
            )
        _visual_note(
            "Failures are warnings, not hidden noise. Recovered samples stay labelled so later analysis can test whether recovery status changes their behaviour."
        )

        if quality.get("failure_types"):
            _show_table(quality["failure_types"])

        section_heading("Backup inventory")
        if backup_inventory["entries"]:
            _show_table(backup_inventory["entries"])
        else:
            st.warning("No verified backup files have been created yet.")

    elif ops_view == "Release":
        section_heading(
            "V1.0 release candidate",
            "Release engineering state and unattended burn-in evidence.",
        )
        manifest = build_release_manifest().as_dict()
        burn = summarize_burn_in(read_burn_in_samples()).as_dict()
        c1, c2, c3 = st.columns(3)
        c1.metric("Version", CHRISTIANIA_VERSION)
        c2.metric("Git state", "Clean" if manifest["git_clean"] else "Dirty / unavailable")
        c3.metric("Burn-in", _status_label(burn["state"]), f"{_fmt_number(burn['duration_hours'], decimals=1)}h")
        section_heading("Release fingerprint")
        st.json(manifest)
        section_heading("Burn-in report")
        st.json(burn)
        st.info(
            "Final V1.0 promotion requires clean-VM deployment, HTTPS/OIDC, real reboot/autostart, "
            "72h unattended burn-in, and independent live Theta timestamp validation."
        )

    else:
        section_heading("System", "Runtime, database and provider diagnostics.")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Schema", f"v{database['schema_version']}")
        c2.metric("Journal", str(database["journal_mode"]).upper())
        c3.metric("Quick check", _status_label(database["quick_check"]))
        c4.metric("FK violations", _fmt_count(database["foreign_key_violation_count"]))

        theta_display = dict(theta_health)
        if theta_display.get("latency_ms") is not None:
            try:
                theta_display["latency_ms"] = round(float(theta_display["latency_ms"]), 1)
            except (TypeError, ValueError):
                theta_display["latency_ms"] = None

        left, right = st.columns(2)
        with left:
            section_heading("Runtime clock")
            st.json(
                {
                    "market_clock": market_clock,
                    "daemon_health": daemon_health,
                    "theta_health": theta_display,
                }
            )
        with right:
            section_heading("Theta timestamp semantics")
            st.json(snapshot.get("theta_timestamp_semantics"))

        section_heading(
            "Provider roles",
            "Real configured provider names; no exchange/tape names are substituted for vendors.",
        )
        _show_table(
            [
                {
                    "provider": "Massive",
                    "role": "Listing/reference frame and snapshot/model enrichment",
                    "runtime_state": "Not independently probed on this screen",
                },
                {
                    "provider": "ThetaData",
                    "role": "Local live options NBBO / Greeks / IV provider",
                    "runtime_state": _status_label(theta_health.get("state")),
                },
                {
                    "provider": "Saxo",
                    "role": "Broker identity/reference; V1 has no order path",
                    "runtime_state": "Execution disabled",
                },
            ]
        )
        st.caption(
            "Provider labels identify vendors. Exchange or tape names appear only when the stored source field actually represents one."
        )

        section_heading("Database path")
        st.code(database["path"], language=None)

        section_heading("Daemon lease")
        if snapshot["daemon_lock"]:
            st.json(snapshot["daemon_lock"])
        else:
            st.warning("No active daemon lease is recorded.")
