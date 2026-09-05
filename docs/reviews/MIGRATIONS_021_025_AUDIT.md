# Migration 021–025 V1 Governance Audit

Reviewed for V1 release engineering; migrations are intentionally unchanged.

- **021** local-surface robustness: descriptive/cross-date robustness structures; p-values/FDR/decision flags are schema-constrained disabled.
- **022** timing reconstruction + calibration readiness: reconstructs timing from persisted evidence and maintains p-value/FDR/decision firewalls.
- **023** calibration validity + Theta timestamp semantics: distinguishes `DOCUMENTED_CONTRACT_VALIDATED_NOT_LIVE_PROBED` from `DOCUMENTED_AND_LIVE_VALIDATED`; decision remains disabled.
- **024** model registry/prospective freeze: roles separate frozen primary/challenger/reserved models; admission and decision flags are schema-constrained disabled; discovery/prospective phases are explicitly partitioned.
- **025** recovery provenance: adds structured recovery error columns and exposes clean/recovered/retry-not-recovered states in prospective partition v2 without changing model/threshold/admission logic.

Package 6 adds regression contracts that scan these migration definitions so these governance invariants cannot silently disappear in a future edit.
