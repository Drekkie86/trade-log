# Hostile-review hardening v9

Addresses the 2026-08-31 independent review blockers.

- NULL-safe shadow lifecycle transition enforcement.
- Raw-SQL bypass regression test.
- First pin event must be PIN.
- Underlying-scoped active-pin view.
- Durable append-only unmatched/provider-only contract evidence.
- Massive SNAPSHOT_ONLY persistence.
- ThetaData THETA_QUOTE_ONLY / THETA_GREEK_ONLY discovery and persistence.
- Native schema no longer deletes schema-version history.
- Expected schema version moves to v9.

The existing `provider_observation_availability.reference_contract_id`
remains non-null. Provider-only identities use a dedicated anomaly table
instead of weakening the meaning of evidence attached to known references.

Reason codes remain observational, not causal.
