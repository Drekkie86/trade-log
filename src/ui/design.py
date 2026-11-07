"""Christiania design system: tokens, global CSS, table builder and SVG charts.

Table rules applied everywhere:
  * text left-aligned, numbers right-aligned, headers aligned with their data
  * tabular figures, one precision per column, units in the header not the cell
  * horizontal hairlines only, no zebra striping, no vertical rules
  * related columns grouped under a spanning header
  * at most one emphasised column per table (the one the rows are ranked by)
  * colour is a secondary cue; signs and words carry the meaning
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from html import escape
from typing import Any, Callable, Sequence

import streamlit as st

HARBOUR = "#0D1F2D"
DEEP = "#13293B"
RULE = "#25415A"
PARCHMENT = "#ECE4D3"
FOG = "#8FA4B4"
BRASS = "#C9A35B"
GAIN = "#74C7A4"
LOSS = "#E58A6E"

FONTS = ('<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
         '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:'
         'wght@400;500;600&family=Spectral:wght@500;600&display=swap">')

CSS = f"""
<style>

:root {{
  --harbour: {HARBOUR}; --deep: {DEEP}; --rule: {RULE}; --parchment: {PARCHMENT};
  --fog: {FOG}; --brass: {BRASS}; --gain: {GAIN}; --loss: {LOSS};
}}
html, body, .stApp {{ font-family: 'IBM Plex Sans', system-ui, sans-serif; }}
.stApp p, .stApp label, .stApp input, .stApp button p, [data-testid="stMarkdownContainer"] {{
  font-family: 'IBM Plex Sans', system-ui, sans-serif; }}
.stApp {{ background: var(--harbour); color: var(--parchment); }}
[data-testid="stHeader"] {{ background: transparent; }}
[data-testid="stSidebar"] {{ background: var(--deep); border-right: 1px solid var(--rule); }}
[data-testid="stSidebar"] [data-testid="stImage"] {{ padding: 0 1.2rem; }}
.block-container {{ padding-top: 2.2rem; max-width: 1180px; }}
a {{ color: var(--brass); }}
:focus-visible {{ outline: 2px solid var(--brass); outline-offset: 2px; }}

/* Page head: title left, freshness right, on one baseline */
.chr-head {{ display: flex; align-items: baseline; justify-content: space-between;
  gap: 2rem; border-bottom: 1px solid var(--rule); padding-bottom: .7rem; margin-bottom: .4rem; }}
.chr-head h1 {{ font-family: 'Spectral', Georgia, serif; font-weight: 600; font-size: 2.1rem;
  letter-spacing: -.01em; margin: 0; padding: 0; color: var(--parchment); }}
.chr-head .fresh {{ color: var(--fog); font-size: .9rem; text-align: right; white-space: nowrap; }}
.chr-head .fresh.stale {{ color: var(--loss); }}
.chr-lede {{ color: var(--fog); font-size: .98rem; max-width: 70ch; margin: .2rem 0 1.4rem; }}
.chr-h2 {{ font-family: 'Spectral', Georgia, serif; font-weight: 500; font-size: 1.35rem;
  line-height: 1.3; margin: 2.2rem 0 .5rem; color: var(--parchment); }}
.chr-note {{ color: var(--fog); font-size: .88rem; max-width: 80ch; margin-top: .5rem; }}
.chr-verdict {{ font-size: 1.15rem; max-width: 70ch; margin: .6rem 0 1.2rem;
  padding-left: .9rem; border-left: 3px solid var(--fog); }}
.chr-verdict.good {{ border-color: var(--gain); }}
.chr-verdict.bad {{ border-color: var(--loss); }}
.chr-verdict.wait {{ border-color: var(--brass); }}

/* Tables (scoped under the markdown container to beat Streamlit's table CSS) */
.chr-table-wrap {{ overflow-x: auto; margin: .3rem 0 .8rem; }}
[data-testid="stMarkdownContainer"] table.chr,
[data-testid="stMarkdownContainer"] table.chr th,
[data-testid="stMarkdownContainer"] table.chr td,
[data-testid="stMarkdownContainer"] table.chr tr {{
  border: none !important; background: transparent; }}
[data-testid="stMarkdownContainer"] table.chr th {{ border-bottom: 1px solid var(--rule) !important; }}
[data-testid="stMarkdownContainer"] table.chr thead tr.groups th.blank {{ border-bottom: none !important; }}
[data-testid="stMarkdownContainer"] table.chr td {{ border-bottom: 1px solid rgba(37,65,90,.55) !important; }}
[data-testid="stMarkdownContainer"] table.chr tr.sel td {{ background: rgba(201,163,91,.07) !important; }}
table.chr td.r, table.chr th.r, table.chr td.nw {{ white-space: nowrap; }}
table.chr td.wide {{ min-width: 15rem; }}
table.chr {{ width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums lining-nums;
  font-size: .93rem; color: var(--parchment); }}
table.chr th {{ font-weight: 500; color: var(--fog); font-size: .82rem; padding: .35rem .55rem;
  border-bottom: 1px solid var(--rule); white-space: nowrap; vertical-align: bottom; }}
table.chr thead tr.groups th {{ color: var(--parchment); font-size: .8rem; border-bottom: 1px solid var(--rule);
  padding-bottom: .2rem; text-align: center; }}
table.chr thead tr.groups th.blank {{ border-bottom: none; }}
table.chr td {{ padding: .6rem .55rem; border-bottom: 1px solid rgba(37,65,90,.6); vertical-align: top; }}
table.chr tbody tr:last-child td {{ border-bottom: 1px solid var(--rule); }}
table.chr .r {{ text-align: right; }}
table.chr .l {{ text-align: left; }}
table.chr .c {{ text-align: center; }}
table.chr .gs {{ padding-left: 1.2rem; }}
table.chr td.key {{ color: var(--brass); font-weight: 600; }}
table.chr tr.sel td {{ background: rgba(201,163,91,.08); }}
table.chr tr.sel td:first-child {{ box-shadow: inset 3px 0 0 var(--brass); }}
table.chr .sub {{ display: block; color: var(--fog); font-size: .82rem; margin-top: .15rem; }}
table.chr .tick {{ font-weight: 600; }}
table.chr .rank {{ color: var(--fog); width: 2rem; }}
table.chr .pos {{ color: var(--gain); }}
table.chr .neg {{ color: var(--loss); }}
table.chr .muted {{ color: var(--fog); }}
.bar {{ display: inline-block; height: .45rem; background: var(--brass); opacity: .75;
  vertical-align: middle; margin-left: .5rem; border-radius: 1px; }}
.dot {{ display: inline-block; width: .55rem; height: .55rem; border-radius: 50%; margin-right: .5rem; }}
.dot.ok {{ background: var(--gain); }} .dot.bad {{ background: var(--loss); }} .dot.unk {{ background: var(--fog); }}

/* Detail panel */
.chr-detail h3 {{ font-family: 'Spectral', Georgia, serif; font-weight: 500; font-size: 1.3rem; margin: 0 0 .2rem; }}
.chr-detail p {{ max-width: 68ch; line-height: 1.55; }}
.chr-limit {{ font-size: 1.05rem; margin: .8rem 0 .2rem; }}
.chr-limit strong {{ color: var(--brass); font-size: 1.25rem; }}
.chr-warn {{ color: var(--loss); }}

/* Native widgets tuned to the palette */
[data-testid="stSidebar"] [role="radiogroup"] label p {{ font-size: 1rem; }}
div[data-testid="stSegmentedControl"] button[aria-checked="true"],
button[kind="segmented_controlActive"] {{ border-color: var(--brass) !important; color: var(--brass) !important; }}
.chr-head {{ flex-wrap: wrap; }}
@media (max-width: 700px) {{
  .chr-head h1 {{ font-size: 1.7rem; }}
  .chr-head .fresh {{ white-space: normal; text-align: left; }}
  table.chr .opt, table.chr .bar {{ display: none; }}
  table.chr thead tr.groups {{ display: none; }}
  table.chr td.wide {{ min-width: 10rem; }}
  .block-container {{ padding-left: 1rem; padding-right: 1rem; }}
}}
@media (prefers-reduced-motion: reduce) {{ * {{ transition: none !important; animation: none !important; }} }}
</style>
"""


def inject() -> None:
    st.html(FONTS + CSS)


def html(body: str) -> None:
    st.markdown(body, unsafe_allow_html=True)


# ------------------------------------------------------------------ formatting
def finite(v: Any) -> bool:
    return v is not None and isinstance(v, (int, float)) and math.isfinite(float(v))


def money(v: Any, *, signed: bool = False, decimals: int = 0) -> str:
    if not finite(v):
        return "–"
    v = float(v)
    body = f"{abs(v):,.{decimals}f}"
    if v < 0 and round(abs(v), decimals) != 0:
        return f"−{body}"
    return f"+{body}" if signed and round(v, decimals) != 0 else body


def usd(v: Any, *, signed: bool = False, decimals: int = 0) -> str:
    """Currency in running text: sign before the symbol (+$55, −$11)."""
    text = money(v, signed=signed, decimals=decimals)
    if text[:1] in "+−":
        return text[0] + "$" + text[1:]
    return "–" if text == "–" else "$" + text


def percent(v: Any, decimals: int = 0) -> str:
    return "–" if not finite(v) else f"{float(v) * 100:.{decimals}f}"


def tone(v: Any, decimals: int = 0) -> str:
    """Colour class matching what is displayed: a value shown as 0 is neutral."""
    if not finite(v) or round(float(v), decimals) == 0:
        return ""
    return "pos" if float(v) > 0 else "neg"


# ---------------------------------------------------------------------- tables
@dataclass(frozen=True)
class Col:
    key: str
    label: str
    align: str = "l"                 # l | r | c
    render: Callable[[dict], str] | None = None   # returns trusted HTML
    css: Callable[[dict], str] | None = None
    group_start: bool = False
    emphasis: bool = False
    cls: str = ""


def table(cols: Sequence[Col], rows: Sequence[dict], *,
          groups: Sequence[tuple[str, int]] | None = None,
          selected: int | None = None) -> str:
    """Build an HTML table. Cell text is escaped unless a renderer supplies HTML."""
    head = []
    if groups:
        cells = []
        for label, span in groups:
            cls = "blank" if not label else ""
            cells.append(f'<th colspan="{span}" class="{cls}">{escape(label)}</th>')
        head.append(f'<tr class="groups">{"".join(cells)}</tr>')
    head.append("<tr>" + "".join(
        f'<th class="{c.align}{" gs" if c.group_start else ""} {c.cls}" scope="col">'
        f'{escape(c.label)}</th>'
        for c in cols) + "</tr>")
    body = []
    for i, row in enumerate(rows):
        tds = []
        for c in cols:
            content = c.render(row) if c.render else escape(str(row.get(c.key, "")))
            classes = [c.align]
            if c.group_start:
                classes.append("gs")
            if c.emphasis:
                classes.append("key")
            if c.cls:
                classes.append(c.cls)
            if c.css:
                classes.append(c.css(row))
            tds.append(f'<td class="{" ".join(x for x in classes if x)}">{content}</td>')
        cls = ' class="sel"' if selected is not None and i == selected else ""
        body.append(f"<tr{cls}>{''.join(tds)}</tr>")
    return (f'<div class="chr-table-wrap"><table class="chr"><thead>{"".join(head)}</thead>'
            f'<tbody>{"".join(body)}</tbody></table></div>')


def bar(value: float, max_value: float, width_rem: float = 4.0) -> str:
    if not (finite(value) and finite(max_value)) or max_value <= 0:
        return ""
    w = max(0.15, min(1.0, float(value) / float(max_value))) * width_rem
    return f'<span class="bar" style="width:{w:.2f}rem"></span>'


# ---------------------------------------------------------------------- charts
def _scale(lo: float, hi: float, a: float, b: float) -> Callable[[float], float]:
    span = (hi - lo) or 1.0
    return lambda v: a + (v - lo) / span * (b - a)


def _nice_ticks(lo: float, hi: float, n: int = 5) -> list[float]:
    span = hi - lo
    if span <= 0:
        return [lo]
    raw = span / n
    mag = 10 ** math.floor(math.log10(raw))
    step = min((s * mag for s in (1, 2, 2.5, 5, 10) if s * mag >= raw), default=raw)
    start = math.ceil(lo / step) * step
    out, v = [], start
    while v <= hi + 1e-9:
        out.append(round(v, 10))
        v += step
    return out


def payoff_svg(legs: Sequence[dict], entry_cash: float, commission: float, *,
               spot: float | None, breakevens: Sequence[float],
               sigma_move: float | None, width: int = 560, height: int = 320) -> str:
    """P&L at expiry against the underlying price, one lot."""
    strikes = sorted({float(l["strike"]) for l in legs})
    centre = spot or (strikes[0] + strikes[-1]) / 2
    half = max((strikes[-1] - strikes[0]) * 1.1, centre * (sigma_move or 0.05) * 2.6,
               centre * 0.02)
    lo, hi = centre - half, centre + half

    def pnl(s: float) -> float:
        pay = 0.0
        for l in legs:
            k = float(l["strike"])
            pay += int(l["side"]) * (max(0.0, s - k) if l["right"] == "C" else max(0.0, k - s))
        return pay * 100 + entry_cash - commission

    xs = sorted({lo, hi, *[k for k in strikes if lo < k < hi], *[b for b in breakevens if lo < b < hi]})
    ys = [pnl(x) for x in xs]
    ymin, ymax = min(ys + [0.0]), max(ys + [0.0])
    pad_y = (ymax - ymin) * 0.12 or 10
    ymin, ymax = ymin - pad_y, ymax + pad_y
    L, R, T, B = 64, 16, 14, 34
    X = _scale(lo, hi, L, width - R)
    Y = _scale(ymin, ymax, height - B, T)
    parts = [f'<svg viewBox="0 0 {width} {height}" width="100%" role="img" '
             f'aria-label="Profit or loss at expiry by underlying price" '
             f'style="font-family:IBM Plex Sans,sans-serif;font-variant-numeric:tabular-nums">']
    # one-standard-deviation band at the delivered-variance width
    if spot and sigma_move:
        a, b = spot * math.exp(-sigma_move), spot * math.exp(sigma_move)
        parts.append(f'<rect x="{X(max(a, lo)):.1f}" y="{T}" width="{X(min(b, hi)) - X(max(a, lo)):.1f}" '
                     f'height="{height - B - T}" fill="{PARCHMENT}" opacity="0.05"/>')
        parts.append(f'<text x="{X(max(a, lo)) + 4:.1f}" y="{height - B - 6}" fill="{FOG}" '
                     f'font-size="12.5">one standard deviation</text>')
    # gridlines and y labels
    for t in _nice_ticks(ymin, ymax, 4):
        parts.append(f'<line x1="{L}" x2="{width - R}" y1="{Y(t):.1f}" y2="{Y(t):.1f}" '
                     f'stroke="{RULE}" stroke-width="{1.4 if t == 0 else 0.6}"/>')
        parts.append(f'<text x="{L - 8}" y="{Y(t) + 4:.1f}" fill="{FOG}" font-size="12.5" '
                     f'text-anchor="end">{money(t, signed=True)}</text>')
    for t in _nice_ticks(lo, hi, 6):
        parts.append(f'<text x="{X(t):.1f}" y="{height - 12}" fill="{FOG}" font-size="12.5" '
                     f'text-anchor="middle">{t:g}</text>')
    # profit / loss fills, split at zero
    zero = Y(0.0)
    pts = " ".join(f"{X(x):.1f},{Y(y):.1f}" for x, y in zip(xs, ys))
    area = f"{X(xs[0]):.1f},{zero:.1f} {pts} {X(xs[-1]):.1f},{zero:.1f}"
    parts.append(f'<clipPath id="above"><rect x="0" y="0" width="{width}" height="{zero:.1f}"/></clipPath>')
    parts.append(f'<clipPath id="below"><rect x="0" y="{zero:.1f}" width="{width}" height="{height}"/></clipPath>')
    parts.append(f'<polygon points="{area}" fill="{GAIN}" opacity="0.18" clip-path="url(#above)"/>')
    parts.append(f'<polygon points="{area}" fill="{LOSS}" opacity="0.13" clip-path="url(#below)"/>')
    parts.append(f'<polyline points="{pts}" fill="none" stroke="{PARCHMENT}" stroke-width="2"/>')
    for b in breakevens:
        if lo < b < hi:
            parts.append(f'<circle cx="{X(b):.1f}" cy="{zero:.1f}" r="3.5" fill="{PARCHMENT}"/>')
            parts.append(f'<text x="{X(b):.1f}" y="{zero + 18:.1f}" fill="{PARCHMENT}" font-size="12.5" '
                         f'text-anchor="middle">{b:g}</text>')
    if spot and lo < spot < hi:
        parts.append(f'<line x1="{X(spot):.1f}" x2="{X(spot):.1f}" y1="{T}" y2="{height - B}" '
                     f'stroke="{BRASS}" stroke-width="1.2" stroke-dasharray="3 3"/>')
        parts.append(f'<text x="{X(spot) + 5:.1f}" y="{T + 12}" fill="{BRASS}" '
                     f'font-size="12.5">now {spot:,.2f}</text>')
    parts.append("</svg>")
    return "".join(parts)


def line_svg(points: Sequence[tuple[str, float]], *, width: int = 900, height: int = 220) -> str:
    """Cumulative series as a step line with a zero rule. Labels are dates."""
    if not points:
        return ""
    ys = [p[1] for p in points]
    ymin, ymax = min(ys + [0.0]), max(ys + [0.0])
    pad = (ymax - ymin) * 0.12 or 10
    ymin, ymax = ymin - pad, ymax + pad
    L, R, T, B = 64, 16, 10, 28
    n = len(points)
    X = _scale(0, max(n - 1, 1), L, width - R)
    Y = _scale(ymin, ymax, height - B, T)
    parts = [f'<svg viewBox="0 0 {width} {height}" width="100%" role="img" '
             f'aria-label="Cumulative settled profit and loss" '
             f'style="font-family:IBM Plex Sans,sans-serif;font-variant-numeric:tabular-nums">']
    for t in _nice_ticks(ymin, ymax, 4):
        parts.append(f'<line x1="{L}" x2="{width - R}" y1="{Y(t):.1f}" y2="{Y(t):.1f}" '
                     f'stroke="{RULE}" stroke-width="{1.4 if t == 0 else 0.6}"/>')
        parts.append(f'<text x="{L - 8}" y="{Y(t) + 4:.1f}" fill="{FOG}" font-size="12.5" '
                     f'text-anchor="end">{money(t, signed=True)}</text>')
    path = []
    for i, (_, y) in enumerate(points):
        if i == 0:
            path.append(f"M{X(0):.1f},{Y(0):.1f} L{X(0):.1f},{Y(y):.1f}")
        else:
            path.append(f"L{X(i):.1f},{Y(points[i - 1][1]):.1f} L{X(i):.1f},{Y(y):.1f}")
    colour = GAIN if ys[-1] >= 0 else LOSS
    parts.append(f'<path d="{" ".join(path)}" fill="none" stroke="{colour}" stroke-width="2"/>')
    for i in sorted({0, n - 1, *range(0, n, max(1, n // 6))}):
        anchor = "start" if i == 0 else "end" if i == n - 1 else "middle"
        parts.append(f'<text x="{X(i):.1f}" y="{height - 8}" fill="{FOG}" font-size="12.5" '
                     f'text-anchor="{anchor}">{escape(points[i][0])}</text>')
    parts.append("</svg>")
    return "".join(parts)
