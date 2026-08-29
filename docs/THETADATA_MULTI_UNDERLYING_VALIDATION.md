# Christiania — Multi-underlying provider validation

This read-only check generalizes the successful AAPL reconciliation to the
Cohort 002 trio:

- AAPL
- XOM
- JPM

Run:

`python validate_thetadata_massive_universe.py 2026-08-28`

The desired result is:

- zero Massive-only identities;
- zero ThetaData-only nonexpired identities;
- zero identity-key failures;
- zero duplicate canonical identities.

ThetaData-only already-expired contracts are expected because ThetaData is
historical while Massive is queried as a current snapshot source.

If all three pass, Christiania has enough evidence to proceed to a historical
ThetaData staging importer without adding Saxo to the bulk path.
