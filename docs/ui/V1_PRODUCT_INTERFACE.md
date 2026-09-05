# Christiania V1 Product Interface

Package 9 turns the existing Streamlit command deck into the branded Christiania V1 browser interface.

## Product principles

- The updated Christiania nautical/Copenhagen/Lovecraftian emblem in `assets/christiania_logo.png` is the authoritative product logo.
- The UI is a research workstation, not a broker terminal.
- `OBSERVATIONAL ONLY` and `not trade signals` remain visible product-level warnings.
- The main engine, Shadow Lab and Storm Cellar / 0DTE Lab remain visually and architecturally distinct.
- The Storm Cellar / 0DTE Lab is experimental, tiny/capped-risk, defined-risk and explicitly not part of the core engine.
- Quantitative challenger models remain research-only and decision/admission disabled.
- Product readiness and scientific maturity are shown separately.
- No external font, CSS or JavaScript CDN is required for the V1 theme.

## Navigation

The V1 product information architecture is:

1. Dashboard
2. Research Runs
3. Calibration
4. Observations
5. Shadow Lab
6. Quant Models
7. Storm Cellar / 0DTE Lab
8. Ops
   - Readiness
   - Release
   - System

## Branding

The V1 palette is deep navy, Copenhagen blue/teal, brass/gold, warm ivory, green for healthy states, amber for caution and red only for failure or the isolated speculative-lab boundary.

The interface uses the logo and restrained nautical ornamentation to establish identity without compromising data density or readability.


## Package 9.1 usability refinement

The V1 interface now keeps the runtime snapshot in the Streamlit session so navigation
does not repeatedly invoke provider/database collection on every page selection. The
operator can refresh explicitly, and a bounded three-minute refresh window prevents a
long-lived session from remaining indefinitely stale.

All research tables translate database field names into human-readable labels. Charts
carry explanatory footnotes that state what is being measured and, where relevant,
what must not be inferred from the visualization.

The Shadow Lab exposes candidate follow-up marks over time. Current independent-leg
liquidation stress marks remain explicitly distinct from validated package outcomes;
`outcome_eligible` is surfaced rather than silently treating every mark as proof that a
candidate thesis was right.

## UI semantic integrity

Christiania's presentation may be theatrical; its claims may not be. **Aesthetic confidence must never imply scientific confidence.**

V1 therefore enforces these interface rules:

- calibration evidence is never shown as decision/trading readiness while governance disables decisions or admission;
- a friendly hypothesis label is only a reviewed alias and is displayed together with the exact **Backend hypothesis ID**;
- model aliases likewise retain the versioned backend model ID;
- unknown hypothesis/model identifiers fall back to their exact stored value rather than receiving invented strategy names;
- vendor labels use the real provider identities **Massive / ThetaData / Saxo**; exchange/tape names are shown only when a stored source field actually means an exchange/tape;
- absent evidence is rendered as an explicit empty state or dash, never as fabricated-looking activity;
- no dashboard metric exists to provide an aspirational target count.

The governing rule is: fun in presentation, deadly serious in numbers.


## Package 9.3 — semantic follow-up

The global hero is intentionally minimal: logo/sidebar plus the Christiania name.
Research warnings are shown where they are relevant rather than as repetitive global copy.

Shadow Lab exposes a candidate-level lifecycle and keeps two outcomes separate:
- thesis assessment, which remains `NOT YET SCORED` until explicit scoring evidence exists;
- validated trade result, which is derived only from `outcome_eligible = 1` marks.

A profitable stress mark is never treated as proof that the thesis was correct.


## Package 9.4 — critical interface review corrections

Package 9.4 turns the external UI review into standing product contracts rather than
one-off wording patches.

- The dashboard reads the actual market-clock contract: `next_sample_at` and the nested
  `session.session_date`. Missing data is no longer caused by stale UI key names.
- Research-run `outcome_mark_count` is labeled **Marks this cycle**, reflecting that it is
  the number of outcome marks written by that daemon iteration rather than an unlabeled
  running total.
- Compact dataframes expose a **Full text / identifiers** expansion whenever long values,
  hashes, paths, notes, details or admission labels may be visually shortened. Safety
  language must remain recoverable in full.
- Readiness, release and system diagnostics are consolidated under **Ops**, reducing
  top-level navigation while preserving distinct operator views.
- Failure/orphan and underlying-failure counts receive warning semantics rather than
  neutral metric treatment. Decorative up-arrows are not used to imply positive movement.
- The speculative wing is named **Storm Cellar / 0DTE Lab**. The sidebar motto
  `NO CRYING IN THE CASINO` remains branding; the high-risk research surface itself is
  not branded as a casino.
- Theta latency is rounded for operator display while the underlying health contract is
  unchanged.
- Streamlit width calls use the current `width="stretch"` API.

## Package 9.5 — interaction and readability

- Human-facing counts use Belgian-style grouping (`12.345`) and decimals use a comma (`12,4`) where decimals are meaningful. IDs, strikes and exact stored scientific values are not reformatted merely for decoration.
- Major metrics, charts and tables carry small explanatory notes that state what the visual means and, where important, what must not be inferred from it.
- Research-facing selection is view-only. Selecting a row or chart mark never changes admission, decision, evidence or stored research state.
- Surfaced Observations supports Power-BI-style cross-filtering: a row or residual bar selection filters the other observation visuals by the selected underlying/direction/right, with an explicit active-filter strip and Clear filters action.
- Research Runs supports row selection and narrows run-specific failure diagnostics when a matching research run exists.
- Interactive chart selection uses Streamlit's Vega-Lite selection contract; no extra JavaScript or external chart runtime is added.


## Package 10 — Decision Desk and hard live-use gates

The Decision Desk is Christiania's synthesis surface. It brings together the persisted anomaly, exact shadow structure, admission evidence, follow-up marks, settlement classification, risk controls and the full research-only quantitative model suite for one selected candidate.

Its central rule is **NO TRADE is always a valid output**. The screen cannot bypass the frozen scientific governance. A high residual, attractive model value or profitable shadow mark cannot override a hard blocker.

### Cash-settlement rule

V1 live/manual-review eligibility fails closed. A contract must be on Christiania's explicit verified cash-settled product allow-list. The initial list is deliberately tiny: SPX and XSP, verified from Cboe product documentation on 2026-09-05. A ticker not on the list is not inferred to be cash-settled. American-style or conflicting metadata is blocking. This rule exists to prevent a small options experiment from unexpectedly creating a delivered share position.

### Risk and stop rule

The fixed EUR 500 active-bankroll cap remains unchanged. The Decision Desk additionally requires an explicit session-level per-trade risk budget and a planned loss-trigger fraction before a candidate can clear the risk gate. Zero/unconfigured controls fail closed. The stop threshold is explicitly described as a monitoring rule rather than a guaranteed execution price; defined-risk maximum loss remains the first line of protection.

### Model dossier

The Decision Desk runs the full research model suite only for the selected candidate and only from stored candidate/quote/model inputs. It does not invent missing spot, IV, rate, dividend yield or entry prices. Model prices are aggregated across the actual persisted multi-leg structure. Model consensus and disagreement remain diagnostic evidence; Christiania explicitly labels probability-weighted expected value as not calibrated for decision use.

### Research rank versus recommendation

The review board orders candidates for investigation using transparent stored evidence (cash-settlement eligibility, shadow admission, model-input completeness, validated outcomes, mark count and anomaly magnitude). This is a **research-review order**, not a probability-of-profit score and not a live-trade leaderboard.
