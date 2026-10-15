# Gate C scoring fail-closed stopgap — independent receipts required

Status: draft-only code safeguard, no production deployment.

As of 11 Oct 2026, production has zero validated package outcomes. The prior
shadow lifecycle checked only whether a mark had measurement_role
VALIDATED_PACKAGE_OUTCOME and outcome_eligible=1. A database row with those
flags can be fabricated in a test without any independent broker response
or execution evidence; the existing test incorrectly treated that as a
legitimate transition to SCORED.

This change disables automatic SCORED transitions until we implement and
independently test an authenticated, immutable, source-linked package
entry/exit verification process. It does not discard marks, alter archived
observations or change CLOSED_OR_EXPIRED transition behavior. It does not
generate NO TRADE outcomes, broker orders, or positive P&L. The safest
temporary output is therefore an honest not-yet-scored state.

To re-enable SCORED, a subsequent reviewed change must:
1. Link immutable, independently source-authenticated package entry and
   exit receipts to a specific candidate, account/simulation environment,
   complete UIC/quantity/side set, and predeclared exit rule.
2. Verify timestamps and as-of order, currency, gross/net economics, fees,
   assignment and settlement, with rejected/missing opportunities retained.
3. Check provenance against an external broker/simulation verifier, not
   merely a caller-provided validity bit or a copied source string.
4. Enforce this in a dedicated append-only journal and scorer, with
   negative, malformed, replay, duplicate, tampered and insufficient
   receipt cases. No manual override based solely on row flags.
5. Pass exact-main CI, performance budgets, migration safety, rollback
   and production preflight before release. Only then restore scoring.

This is a deliberately conservative interim safety closure; Gate C #98
is not passed by disabling scoring. The independent verified outcome
pipeline remains implementation work.
