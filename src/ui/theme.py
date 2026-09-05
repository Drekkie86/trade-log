from __future__ import annotations

import streamlit as st

BRAND_COLORS = {
    "navy": "#031522",
    "navy_2": "#06253A",
    "panel": "#08283E",
    "panel_2": "#0B3048",
    "gold": "#D9A84E",
    "gold_soft": "#F1D08A",
    "cyan": "#2EC4D6",
    "teal": "#1A8FA6",
    "green": "#52D987",
    "amber": "#E9B44C",
    "red": "#F0645A",
    "text": "#F4F0E7",
    "muted": "#9EB4C3",
    "line": "#15506F",
}

_THEME_CSS = r"""
<style>
:root {
  --chr-navy: #031522;
  --chr-navy-2: #06253A;
  --chr-panel: #08283E;
  --chr-panel-2: #0B3048;
  --chr-gold: #D9A84E;
  --chr-gold-soft: #F1D08A;
  --chr-cyan: #2EC4D6;
  --chr-teal: #1A8FA6;
  --chr-green: #52D987;
  --chr-amber: #E9B44C;
  --chr-red: #F0645A;
  --chr-text: #F4F0E7;
  --chr-muted: #9EB4C3;
  --chr-line: #15506F;
}

html, body, [data-testid="stAppViewContainer"] {
  background:
    radial-gradient(circle at 84% 8%, rgba(25, 108, 136, 0.22), transparent 28%),
    linear-gradient(180deg, #031522 0%, #021019 100%);
  color: var(--chr-text);
}

[data-testid="stHeader"] {
  background: rgba(3, 21, 34, 0.90);
  border-bottom: 1px solid rgba(217, 168, 78, 0.18);
}

[data-testid="stSidebar"] {
  background:
    radial-gradient(circle at 50% 92%, rgba(24, 121, 145, 0.20), transparent 28%),
    linear-gradient(180deg, #041A2A 0%, #02111A 100%);
  border-right: 1px solid rgba(217, 168, 78, 0.42);
}

[data-testid="stSidebar"] > div:first-child {
  padding-top: 1rem;
}

[data-testid="stSidebar"] [role="radiogroup"] label {
  border-radius: 8px;
  padding: 0.32rem 0.55rem;
  margin-bottom: 0.12rem;
}

[data-testid="stSidebar"] [role="radiogroup"] label:hover {
  background: rgba(217, 168, 78, 0.08);
}

[data-testid="stSidebar"] [aria-checked="true"] {
  background: linear-gradient(90deg, rgba(217,168,78,0.18), rgba(46,196,214,0.06));
  border-left: 3px solid var(--chr-gold);
}

.block-container,
[data-testid="stMainBlockContainer"] {
  max-width: 1680px;
  padding-top: 5.75rem !important;
  padding-bottom: 3rem;
}

[data-testid="stSidebar"] {
  min-width: 18rem;
}

[data-testid="stSidebarContent"] {
  padding-top: 0.75rem;
}

h1, h2, h3, .chr-serif {
  font-family: Georgia, 'Times New Roman', serif !important;
  letter-spacing: 0.02em;
}

h1, h2, h3 {
  color: var(--chr-gold-soft) !important;
}

[data-testid="stMetric"] {
  background: linear-gradient(180deg, rgba(8,40,62,0.96), rgba(4,27,42,0.96));
  border: 1px solid rgba(46,196,214,0.35);
  border-radius: 12px;
  padding: 0.85rem 1rem;
  box-shadow: 0 8px 22px rgba(0,0,0,0.18);
}

[data-testid="stMetricLabel"] {
  color: var(--chr-gold-soft);
  font-weight: 600;
}

[data-testid="stMetricValue"] {
  color: var(--chr-text);
}

[data-testid="stDataFrame"], [data-testid="stTable"] {
  border: 1px solid rgba(46,196,214,0.28);
  border-radius: 10px;
  overflow: hidden;
}

[data-testid="stForm"] {
  background: linear-gradient(180deg, rgba(8,40,62,0.88), rgba(4,27,42,0.92));
  border: 1px solid rgba(217,168,78,0.28);
  border-radius: 12px;
  padding: 1rem;
}

.stButton > button, .stDownloadButton > button {
  border: 1px solid rgba(217,168,78,0.70);
  background: linear-gradient(180deg, rgba(22,74,96,0.9), rgba(7,38,56,0.95));
  color: var(--chr-gold-soft);
  border-radius: 8px;
}

.stButton > button:hover, .stDownloadButton > button:hover {
  border-color: var(--chr-gold-soft);
  color: #fff;
}

.chr-hero {
  border: 1px solid rgba(217,168,78,0.45);
  border-radius: 14px;
  padding: 0.75rem 1.25rem;
  margin-bottom: 0.75rem;
  background:
    radial-gradient(circle at 90% 20%, rgba(46,196,214,0.10), transparent 28%),
    linear-gradient(135deg, rgba(8,40,62,0.97), rgba(3,21,34,0.97));
  box-shadow: 0 12px 28px rgba(0,0,0,0.22);
}

.chr-hero-kicker {
  color: var(--chr-gold);
  font-size: 0.72rem;
  letter-spacing: 0.24em;
  text-transform: uppercase;
  font-weight: 700;
}

.chr-hero-title {
  color: var(--chr-gold-soft);
  font-family: Georgia, 'Times New Roman', serif;
  font-size: clamp(1.8rem, 3vw, 2.9rem);
  line-height: 1.05;
  letter-spacing: 0.06em;
  margin: 0.15rem 0 0.35rem;
}

.chr-hero-subtitle {
  color: var(--chr-muted);
  max-width: 900px;
  font-size: 0.95rem;
}

.chr-observation {
  border: 1px solid rgba(217,168,78,0.68);
  background: rgba(5, 29, 43, 0.92);
  border-radius: 9px;
  padding: 0.72rem 0.95rem;
  margin: 0.65rem 0 1rem;
  display: flex;
  gap: 1rem;
  align-items: center;
  flex-wrap: wrap;
}

.chr-observation strong {
  color: var(--chr-gold-soft);
  letter-spacing: 0.16em;
}

.chr-observation span {
  color: var(--chr-muted);
}

.chr-card {
  min-height: 100%;
  border: 1px solid rgba(46,196,214,0.34);
  border-radius: 12px;
  padding: 0.9rem 1rem;
  background: linear-gradient(180deg, rgba(8,40,62,0.96), rgba(4,27,42,0.96));
  box-shadow: 0 9px 24px rgba(0,0,0,0.16);
}

.chr-card-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.6rem;
  margin-bottom: 0.55rem;
  color: var(--chr-gold-soft);
  font-family: Georgia, 'Times New Roman', serif;
  font-size: 1.03rem;
  font-weight: 700;
}

.chr-card-body {
  color: var(--chr-text);
  font-size: 0.9rem;
  line-height: 1.55;
}

.chr-pill {
  display: inline-flex;
  align-items: center;
  gap: 0.36rem;
  border-radius: 999px;
  padding: 0.18rem 0.55rem;
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  border: 1px solid rgba(255,255,255,0.11);
}

.chr-pill.good { background: rgba(82,217,135,0.12); color: #77E6A5; }
.chr-pill.warn { background: rgba(233,180,76,0.12); color: #F1C66A; }
.chr-pill.bad { background: rgba(240,100,90,0.12); color: #F37F77; }
.chr-pill.info { background: rgba(46,196,214,0.12); color: #6ED9E5; }

.chr-dot {
  width: 0.56rem;
  height: 0.56rem;
  border-radius: 50%;
  display: inline-block;
  margin-right: 0.42rem;
  box-shadow: 0 0 10px currentColor;
}

.chr-section {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 1rem;
  margin-top: 1.15rem;
  margin-bottom: 0.55rem;
  padding-bottom: 0.35rem;
  border-bottom: 1px solid rgba(217,168,78,0.22);
}

.chr-section h3 {
  margin: 0;
  color: var(--chr-gold-soft);
}

.chr-section p {
  margin: 0;
  color: var(--chr-muted);
  font-size: 0.82rem;
}

.chr-casino {
  border: 1px solid rgba(240,100,90,0.72);
  border-radius: 12px;
  background: linear-gradient(180deg, rgba(66,27,29,0.78), rgba(34,16,20,0.88));
  padding: 1rem 1.1rem;
  margin-bottom: 1rem;
}

.chr-casino h3 { color: #F0B075 !important; }
.chr-casino strong { color: #F37F77; }

.chr-side-caption {
  text-align: center;
  color: var(--chr-gold);
  letter-spacing: 0.14em;
  font-size: 0.68rem;
  margin-top: 0.35rem;
}

.chr-chart-note {
  margin: -0.1rem 0 0.8rem;
  color: var(--chr-muted);
  font-size: 0.76rem;
  line-height: 1.45;
  border-left: 2px solid rgba(217,168,78,0.38);
  padding: 0.38rem 0.65rem;
  background: rgba(3,21,34,0.34);
  border-radius: 0 6px 6px 0;
}

.chr-side-quote {
  margin: 1.1rem 0 0.4rem;
  padding: 0.85rem;
  text-align: center;
  color: var(--chr-gold-soft);
  font-family: Georgia, 'Times New Roman', serif;
  letter-spacing: 0.08em;
  font-size: 0.78rem;
  border-top: 1px solid rgba(217,168,78,0.25);
  border-bottom: 1px solid rgba(217,168,78,0.25);
}

hr { border-color: rgba(217,168,78,0.18) !important; }
</style>
"""


def inject_christiania_theme() -> None:
    """Install the V1 product theme without relying on external assets/CDNs."""
    st.markdown(_THEME_CSS, unsafe_allow_html=True)
