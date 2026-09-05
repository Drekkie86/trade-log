from __future__ import annotations

from pathlib import Path
import time

import pandas as pd
import streamlit as st

from src.dashboard.read_model import load_command_deck
from src.operations.backup_recovery import inventory_backups
from src.operations.burn_in import read_burn_in_samples, summarize_burn_in
from src.operations.release_manifest import build_release_manifest
from src.operations.v1_readiness import assess_v1_readiness
from src.quant.bench import run_vanilla_bench
from src.quant.registry import catalog as quant_model_catalog
from src.quant.types import QuantInputError, VanillaOption
from src.ui import (
    badge,
    card,
    hero,
    inject_christiania_theme,
    observation_banner,
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
    "outcome_mark_count": "Shadow marks",
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
    "mark_count": "Mark count",
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
    st.dataframe(
        frame,
        use_container_width=True,
        hide_index=True,
        height=height,
    )



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
        st.image(str(LOGO_PATH), use_container_width=True)
    st.markdown(
        '<div class="chr-side-caption">NO CRYING IN THE CASINO</div>',
        unsafe_allow_html=True,
    )
    st.divider()

    page = st.radio(
        "Navigation",
        [
            "⚓ Dashboard",
            "📜 Research Runs",
            "⚙ Calibration",
            "◉ Observations",
            "⚗ Shadow Lab",
            "∑ Quant Models",
            "🎲 Casino / 0DTE Lab",
            "✓ Readiness",
            "◆ Release Status",
            "⚙ System",
        ],
        label_visibility="collapsed",
    )
    page = page.split(" ", 1)[1]

    st.divider()
    if st.button("↻ Refresh deck", use_container_width=True):
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
                    ("Storage & backups", f"{backup_inventory.get('valid_files', 0)} verified", "READY" if backup_inventory.get("valid_files") else "WARN"),
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
                    ("Latency", f"{theta_health.get('latency_ms', '—')} ms", theta_health.get("state")),
                ]
            ),
            badge_label="Operational" if theta_health.get("ready") else _status_label(theta_health.get("state")),
        )

    with c3:
        card(
            "Market clock",
            (
                f'<div style="font-size:2.15rem;font-family:Georgia,serif;color:#F1D08A">{_status_label(market_clock.get("state"))}</div>'
                f'<div style="margin-top:.45rem;color:#9EB4C3">Session date: {_safe(market_clock.get("session_date"))}</div>'
                f'<div style="margin-top:.2rem">Next sample: <strong>{_safe(market_clock.get("next_sample"))}</strong></div>'
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
                    ("Succeeded", str(latest_run.get("succeeded_underlyings", 0) if latest_run else 0), "SUCCESS"),
                    ("Failed", str(latest_run.get("failed_underlyings", 0) if latest_run else 0), "FAIL" if latest_run and latest_run.get("failed_underlyings") else "SUCCESS"),
                ]
            ),
            badge_label="Latest",
            badge_tone="info",
        )

    section_heading("Research pulse", "Prospective evidence grows independently from product readiness.")
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Prospective dates", prospective["independent_dates"], "first review at 5")
    m2.metric("Observation rows", prospective["observation_rows"])
    m3.metric("Surfaced observations", counts["surfaced_total"])
    m4.metric("Shadow candidates", counts["shadow_candidates"])
    m5.metric("Recovered samples", prospective["recovered_samples"], "provenance retained")

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
        st.metric("Registered models", len(registry), f"{enabled} decision-enabled")
        st.caption("Models are maps, not territory. All V1 challengers remain research-only.")

    with lower3:
        section_heading("Verified backups")
        latest_age = backup_inventory.get("latest_valid_age_hours")
        st.metric(
            "Valid backups",
            backup_inventory.get("valid_files", 0),
            "—" if latest_age is None else f"latest {latest_age:.1f}h ago",
        )
        if backup_inventory.get("invalid_files"):
            st.error(f"{backup_inventory['invalid_files']} invalid backup(s)")
        else:
            st.success("Recovery inventory nominal")

elif page == "Research Runs":
    section_heading("Research runs", "Collection cadence, provider outcomes, proposals and marks.")
    if snapshot.get("recent_iterations"):
        _show_table(snapshot["recent_iterations"])
    else:
        st.info("No daemon iterations recorded.")

    c1, c2 = st.columns(2)
    with c1:
        section_heading("Session summary")
        st.json(snapshot.get("session", {}))
    with c2:
        section_heading("Data-quality pulse")
        st.json(quality.get("iteration_window", {}))

    if quality.get("recent_failed_underlyings"):
        section_heading("Recent failed underlying samples", "Failure reasons remain explicit and queryable.")
        _show_table(quality["recent_failed_underlyings"])

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
    c1.metric("Independent dates", prospective["independent_dates"], "first descriptive review at 5")
    c2.metric("Prospective rows", prospective["observation_rows"])
    c3.metric("Recovered samples", prospective["recovered_samples"], "visible covariate")

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
        df = pd.DataFrame(snapshot["recent_anomalies"])
        _show_table(df)
        if "abs_iv_residual" in df:
            st.bar_chart(df[["abs_iv_residual"]].head(25), height=260)
            chart_note(
                "Absolute IV residual for the most recently surfaced observations. "
                "Larger bars mean larger model-versus-observation disagreement, not stronger trade conviction."
            )
    else:
        st.info("No surfaced observations recorded.")

elif page == "Shadow Lab":
    section_heading(
        "Shadow Lab",
        "Candidate follow-up: inception, subsequent marks, validated outcomes, and current evidence state.",
    )
    tracking = snapshot.get("shadow_tracking", {})
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Proposals", counts["proposals_total"], f"{counts['proposals_blocked']} builder-blocked")
    c2.metric("Admitted shadows", counts["admitted_total"], f"{counts['admission_blocked']} blocked")
    c3.metric("Recorded marks", counts["shadow_marks"], f"{tracking.get('marked_candidates', 0)} candidate(s)")
    c4.metric("Validated outcomes", tracking.get("validated_outcomes", 0), "outcome-eligible only")

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
                st.metric("Model range", f"{disagreement['absolute_range']:.4f}")
                st.metric("Consensus mean", f"{disagreement['mean']:.4f}")
                st.metric(
                    "Market − consensus",
                    "—" if disagreement["market_minus_consensus"] is None else f"{disagreement['market_minus_consensus']:.4f}",
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

elif page == "Casino / 0DTE Lab":
    st.markdown(
        """
        <div class="chr-casino">
          <h3>🎲 Casino / 0DTE Lab — EXPERIMENTAL, SEPARATE</h3>
          <p><strong>Casino in spirit, quant in discipline.</strong> Tiny capped risk, defined-risk structures, explicit slippage, jump/event risk, gamma exposure and scenario EV.</p>
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

elif page == "Readiness":
    section_heading("V1 readiness", "Operational readiness is deliberately separate from scientific maturity.")
    c1, c2, c3 = st.columns(3)
    c1.metric("Product state", _status_label(readiness["product_state"]))
    c2.metric(
        "Scientific state",
        _status_label(readiness["scientific_state"]),
        f"{readiness['independent_prospective_dates']} prospective date(s)",
    )
    c3.metric(
        "Latest verified backup",
        "None" if backup_inventory["latest_valid_age_hours"] is None else f"{backup_inventory['latest_valid_age_hours']:.1f}h ago",
        f"{backup_inventory['valid_files']} valid / {backup_inventory['invalid_files']} invalid",
    )

    _show_table(readiness["checks"])

    section_heading("Data-quality pulse")
    q1, q2, q3, q4 = st.columns(4)
    iterations = quality.get("iteration_window", {})
    underlyings = quality.get("underlying_totals", {})
    q1.metric("Recent completed", iterations.get("completed", 0))
    q2.metric("Failed/orphaned", int(iterations.get("failed", 0)) + int(iterations.get("orphaned", 0)))
    q3.metric("Underlying failures", underlyings.get("failed", 0))
    q4.metric("Recovered underlyings", underlyings.get("recovered", 0))

    if quality.get("failure_types"):
        _show_table(quality["failure_types"])

    section_heading("Backup inventory")
    if backup_inventory["entries"]:
        _show_table(backup_inventory["entries"])
    else:
        st.warning("No verified backup files have been created yet.")

elif page == "Release Status":
    section_heading("V1.0 release candidate", "Release engineering state and unattended burn-in evidence.")
    manifest = build_release_manifest().as_dict()
    burn = summarize_burn_in(read_burn_in_samples()).as_dict()
    c1, c2, c3 = st.columns(3)
    c1.metric("Version", CHRISTIANIA_VERSION)
    c2.metric("Git state", "Clean" if manifest["git_clean"] else "Dirty / unavailable")
    c3.metric("Burn-in", _status_label(burn["state"]), f"{burn['duration_hours']:.1f}h")
    section_heading("Release fingerprint")
    st.json(manifest)
    section_heading("Burn-in report")
    st.json(burn)
    st.info(
        "Final V1.0 promotion requires clean-VM deployment, HTTPS/OIDC, real reboot/autostart, "
        "72h unattended burn-in, and independent live Theta timestamp validation."
    )

elif page == "System":
    section_heading("System", "Runtime, database and provider diagnostics.")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Schema", f"v{database['schema_version']}")
    c2.metric("Journal", str(database["journal_mode"]).upper())
    c3.metric("Quick check", _status_label(database["quick_check"]))
    c4.metric("FK violations", database["foreign_key_violation_count"])

    left, right = st.columns(2)
    with left:
        section_heading("Runtime clock")
        st.json(
            {
                "market_clock": market_clock,
                "daemon_health": daemon_health,
                "theta_health": theta_health,
            }
        )
    with right:
        section_heading("Theta timestamp semantics")
        st.json(snapshot.get("theta_timestamp_semantics"))

    section_heading("Provider roles", "Real configured provider names; no exchange/tape names are substituted for vendors.")
    _show_table(
        [
            {{
                "provider": "Massive",
                "role": "Listing/reference frame and snapshot/model enrichment",
                "runtime_state": "Not independently probed on this screen",
            }},
            {{
                "provider": "ThetaData",
                "role": "Local live options NBBO / Greeks / IV provider",
                "runtime_state": _status_label(theta_health.get("state")),
            }},
            {{
                "provider": "Saxo",
                "role": "Broker identity/reference; V1 has no order path",
                "runtime_state": "Execution disabled",
            }},
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
