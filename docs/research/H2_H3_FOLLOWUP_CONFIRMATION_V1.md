# H2/H3 Follow-up Confirmation V1

## Purpose

This package opens a **new, separate prospective confirmation programme** for
Christiania's H2 model-form and H3 market-quality findings.

It does **not** modify, replace, or reset the original H1-H4 prospective
programme. The original clock still begins on **2026-09-04**.

The follow-up programme is frozen through **2026-09-17** and may treat evidence
from **2026-09-18 onward** as prospective only if the explicit freeze is recorded
before any completed 2026-09-18 research run exists.

## Why a separate programme

The Sep-04 through Sep-17 evidence was inspected in depth after the original
prospective checkpoint. That work produced a better-specified follow-up question,
but it also means the new endpoint choices are discovery-informed.

Creating another row in the original V1 freeze table would silently move the
boundary used by the existing "latest freeze" partition view and would
reclassify the original Sep-04 through Sep-17 evidence. Migration 032 therefore
creates a separate follow-up namespace and read surface instead.

## Discovery record carried into the freeze

The freeze stores these facts as **supporting discovery context, not future
confirmation**:

- production V1 nearest-bracket reconstruction:
  - 969,048 evaluable observations;
  - zero geometry mismatches;
  - zero residual mismatches above 1e-12;
  - maximum absolute difference approximately 1.11e-16;
- H2/V2 overlapping population:
  - 965,689 comparable observations;
  - zero missing V1 residuals;
  - zero residual mismatches above 1e-12;
  - the 3,359-observation gap from the 969,048 V1-evaluable population is
    completely reconciled to quadratic-V2 minimum geometry:
    - 835 observations had 3 usable strikes;
    - 2,524 observations had 4 usable strikes;
    - all 3,359 are persisted as `NOT_EVALUABLE` with
      `INSUFFICIENT_USABLE_STRIKES`;
    - zero V2 observations are unexplained or missing;
- raw-vs-raw H2, ALL population:
  - 24 date x DTE cells;
  - local-linear lower median absolute residual in 24/24 cells;
  - local-linear lower q95 absolute residual in 20/24 cells;
  - local-linear better-fraction above 0.5 in 24/24 cells;
  - better-fraction range 54.33% to 68.92%;
- the raw-vs-raw endpoint was selected for symmetry, not because it made H2
  look stronger. The retrospective raw-vs-centred audit was mixed, with the
  centred comparison often producing the higher local-linear better-fraction.
  Examples on the ALL population include:
  - Sep-14 DTE 21-30: raw 66.86% versus centred 68.67%;
  - Sep-16 DTE 31-45: raw 66.22% versus centred 68.08%;
  - Sep-17 DTE 21-30: raw 65.83% versus centred 68.28%.
  Raw-vs-raw is therefore the fairer paired model comparison even where it is
  descriptively less flattering to the challenger;
- the CLEAN lens had stronger descriptive consistency, but its elevation occurred
  after inspecting the discovery period;
- Sep-04 was a genuinely weaker date and remains in the record;
- forcing later dates onto Sep-04's observed sampling schedule did not explain
  the weak Sep-04 result;
- H3 discovery decomposition showed strict worsening-quality monotonicity in:
  - 24/24 spread date x DTE cells;
  - 24/24 Greek-age date x DTE cells.

None of those facts is a prospective result for this follow-up programme.

## H2 follow-up protocol

### Primary population

`ALL_PAIRED_EVALUABLE`

For the same persisted option observation:

- challenger error = absolute persisted V1 nearest-bracket local-linear residual;
- comparator error = absolute **raw** quadratic V2 leave-one-out residual.

The comparison is intentionally raw-vs-raw. It does not use frozen-null
centering on only one side.

The fixed DTE buckets remain:

- DTE 7-13;
- DTE 14-20;
- DTE 21-30;
- DTE 31-45.

The frozen descriptive metric family is:

- median absolute residual;
- q95 absolute residual;
- local-linear better-fraction.

Independent session date is the evidence unit for consistency interpretation.
The large number of option rows is not treated as the independent sample size.

### Secondary population

`spread_to_mid < 0.05 AND abs(greek_age_seconds) <= 1`

This uses thresholds that already existed in frozen H3, but the decision to
emphasize the CLEAN subgroup was made after observing the Sep-04 through Sep-17
decomposition.

Its role is therefore permanently labelled:

`PRESPECIFIED_SECONDARY_DISCOVERY_INFORMED`

It is not promoted to the primary confirmation population.

## H3 follow-up protocol

H3 keeps the original frozen-null-centred quadratic V2 residual basis.

Within each independent session date x DTE cell, the follow-up records mean
absolute centred residual for these pre-existing buckets.

Spread:

1. `< 5%`
2. `5-10%`
3. `10-20%`

Greek age:

1. `<= 1s`
2. `1-5s`
3. `5-30s`

The frozen replication descriptor is strict monotonic increase in residual
scale as market quality worsens.

This is descriptive replication, not a causal estimate.

## Review milestones

The programme has only two frozen review milestones:

- **5 independent fresh dates**: descriptive checkpoint;
- **20 independent fresh dates**: serious research review.

The evaluator uses the **first N eligible dates** for each milestone. It does
not continually redefine the evidence window at dates 6, 7, 8, and so on.

The following remain disabled at both milestones:

- p-values;
- FDR/BH;
- automatic admission changes;
- automatic model promotion;
- candidate-rule changes;
- edge claims;
- trading decisions.

## Frozen implementation identity

The explicit freeze command records the single scanner identity and the single
quadratic V2 identity observed across the Sep-04 through Sep-17 discovery
window.

Future dates count toward this follow-up only when both persisted model
identities match the frozen identity and a paired residual exists.

A future model/version change therefore does not silently contaminate the
follow-up population.

## Prospectivity guard

The freeze command is idempotent once the programme exists.

On first creation it refuses to freeze if any completed research run already
exists on or after **2026-09-18**.

This is deliberate. A late freeze must fail closed rather than pretend that
already-observed evidence was prospective.

## Operator sequence

After migration 032 is deployed, and before the first Sep-18 research sample:

```powershell
python freeze_h2_h3_followup_confirmation_v1.py
```

The output must show:

- `created: true` on first creation;
- frozen through `2026-09-17`;
- prospective start `2026-09-18`;
- the original H1-H4 freeze referenced as source provenance.

Running the same command again is safe and returns `created: false`.

At or after a frozen review milestone:

```powershell
python report_h2_h3_followup_confirmation_v1.py
```

Before five eligible fresh dates, no H2/H3 milestone evaluation is persisted.

## Scientific boundary

This programme asks:

> Do the H2 model-form advantage and H3 market-quality structure survive a new
> prospectively frozen evidence window under definitions written before seeing
> that window?

It does not ask:

> Has Christiania proven a tradable edge?

Those are different claims.
