# Package D Acceptance Contract — Calibration + Model Tournament + Prospective Shadow V1

Package D may merge only when the full Christiania Quality Gate is green.

## Required acceptance points

- `P(thesis correct)` and `P(trade profitable)` remain separate channels.
- Calibration inputs require immutable observation identity, model identity, channel, probability, binary outcome and independent date.
- Brier score and log loss are implemented with validated probability bounds.
- Reliability/calibration bins preserve sample counts.
- Paired incumbent/challenger comparisons use only common observation keys.
- Paired comparisons reject mismatched outcomes or independent dates.
- Tournament leadership does not create automatic model promotion.
- Promotion eligibility requires explicit sample/date sufficiency and robustness.
- Positive promotion state means review eligibility only.
- Read-only runtime does not mutate the Christiania database.
- Existing prospective freeze and shadow lifecycle are reused rather than overwritten.
- Missing decision-time probabilities are reported as missing, never reconstructed with hindsight.
- Existing p-value/FDR/admission/decision firewalls are not enabled by this package.
- No new edge family is activated.
- No broker execution or trade approval path is added.
- Decision authority remains `NONE_AUTOMATIC_REVIEW_ONLY` or stricter.

## Release boundary

A green Package D is calibration and prospective-evidence infrastructure. It may make a model eligible for a **human promotion review** after sufficient evidence. It may not make a trade eligible for live execution.
