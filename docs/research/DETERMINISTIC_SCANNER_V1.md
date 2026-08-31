# Deterministic Scanner v1

This scanner reads **persisted research evidence** from a completed
`INDEPENDENT_RESEARCH_RUNNER_V1` run.

It does not call market-data providers.

It does not create shadow candidates.

It does not make edge claims.

## Scanner identity

- family: `BASIC_TRADABILITY_V1`
- scanner version: `1.0.0`
- rules: `BASIC_TRADABILITY_RULES_V1`

## Current structural eligibility rules

A persisted option observation is structurally eligible only when:

1. bid and ask exist;
2. bid and ask are non-negative;
3. ask is not below bid;
4. mid is positive;
5. quote freshness is `FRESH`;
6. spread / mid <= 20% by default;
7. ThetaData Greek quality is not BAD/UNKNOWN;
8. delta is present.

The 20% spread/mid threshold is intentionally permissive and should not be
interpreted as a final tradability standard. It exists to create a deterministic
first filter that can be measured against real data.

## Important distinction

`structurally eligible` means:

> this observation has enough basic market/model quality to be considered by a
> later scanner family.

It does not mean:

- mispriced;
- profitable;
- executable;
- liquid enough for our bankroll;
- candidate edge;
- validated edge.

## Why this runs from the database

The scanner is intentionally separated from live acquisition.

That lets Christiania:

- rerun different scanner versions against the same frozen evidence;
- compare rule families without changing the input data;
- measure selection effects;
- avoid provider timing changes contaminating scanner comparisons;
- eventually compare deterministic rules against ML challengers.

## Next step

After tomorrow's first live-session independent research run, run:

```powershell
python .\run_deterministic_scanner.py
```

The resulting eligible set becomes the input to the first *actual hypothesis*
scanner family, which may still produce zero candidates.
