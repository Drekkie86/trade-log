# Christiania V1 Product Interface

Package 9 turns the existing Streamlit command deck into the branded Christiania V1 browser interface.

## Product principles

- The updated Christiania nautical/Copenhagen/Lovecraftian emblem in `assets/christiania_logo.png` is the authoritative product logo.
- The UI is a research workstation, not a broker terminal.
- `OBSERVATIONAL ONLY` and `not trade signals` remain visible product-level warnings.
- The main engine, Shadow Lab and Casino / 0DTE Lab remain visually and architecturally distinct.
- The Casino / 0DTE Lab is experimental, tiny/capped-risk, defined-risk and explicitly not part of the core engine.
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
7. Casino / 0DTE Lab
8. Readiness
9. Release Status
10. System

## Branding

The V1 palette is deep navy, Copenhagen blue/teal, brass/gold, warm ivory, green for healthy states, amber for caution and red only for failure or the isolated Casino boundary.

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
