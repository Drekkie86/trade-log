# Christiania — ThetaData empirical diagnostics v1

Purpose: turn the staging database into descriptive empirical evidence.

Current outputs:

- absolute quoted spread;
- spread / mid;
- half-spread / mid;
- spread distribution by underlying;
- identical-contract next-observed-session mid-to-mid return;
- hypothetical long ask-to-bid return;
- quoted round-trip drag;
- exit-bid availability;
- broad cross-underlying daily return correlation.

Important limitation:

The cross-underlying correlation in v1 is NOT Cohort 002 paired-edge
correlation. It is exploratory correlation of average identical-contract
one-session returns by underlying/date.

Likewise, the next-session matcher uses consecutive completed dates present in
the staging DB. It does not yet use an exchange trading calendar.

No empirical detectability parameter promotion is permitted from this v1
diagnostic alone.
