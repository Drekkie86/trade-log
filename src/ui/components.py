from __future__ import annotations

from html import escape

import streamlit as st


def _tone_for_state(state: str | None) -> str:
    value = str(state or "").upper()
    if any(token in value for token in ("READY", "PASS", "HEALTHY", "COMPLETED", "SUCCESS", "VALID", "OPEN")):
        return "good"
    if any(token in value for token in ("FAIL", "ERROR", "BLOCKED", "INVALID", "ORPHAN", "DOWN", "UNREACHABLE")):
        return "bad"
    if any(token in value for token in ("WARN", "STALE", "RETRY", "PENDING", "ACCUMULATING", "CLOSED")):
        return "warn"
    return "info"


def badge(label: str, *, tone: str | None = None) -> str:
    tone = tone or _tone_for_state(label)
    return f'<span class="chr-pill {escape(tone)}">{escape(str(label))}</span>'


def status_dot(state: str | None) -> str:
    tone = _tone_for_state(state)
    color = {
        "good": "#52D987",
        "warn": "#E9B44C",
        "bad": "#F0645A",
        "info": "#2EC4D6",
    }[tone]
    return f'<span class="chr-dot" style="color:{color};background:{color}"></span>'


def hero(*, version: str, subtitle: str) -> None:
    st.markdown(
        f"""
        <div class="chr-hero">
          <div class="chr-hero-kicker">V1 Research Workstation · {escape(version)}</div>
          <div class="chr-hero-title">CHRISTIANIA</div>
          <div class="chr-hero-subtitle">{escape(subtitle)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def observation_banner() -> None:
    st.markdown(
        """
        <div class="chr-observation">
          <strong>⚓ OBSERVATIONAL ONLY</strong>
          <span>Surfaced anomalies and model disagreement are not trade signals. No broker-order path. Research and calibration only.</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def section_heading(title: str, caption: str | None = None) -> None:
    caption_html = f"<p>{escape(caption)}</p>" if caption else ""
    st.markdown(
        f'<div class="chr-section"><h3>{escape(title)}</h3>{caption_html}</div>',
        unsafe_allow_html=True,
    )



def chart_note(text: str) -> None:
    """Render a compact explanatory footnote below a chart."""
    st.markdown(
        f'<div class="chr-chart-note">↳ {escape(text)}</div>',
        unsafe_allow_html=True,
    )


def card(title: str, body_html: str, *, badge_label: str | None = None, badge_tone: str | None = None) -> None:
    badge_html = badge(badge_label, tone=badge_tone) if badge_label else ""
    st.markdown(
        f"""
        <div class="chr-card">
          <div class="chr-card-title"><span>{escape(title)}</span>{badge_html}</div>
          <div class="chr-card-body">{body_html}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
