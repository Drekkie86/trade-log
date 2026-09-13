# Christiania — Research Command Deck + Programme Family Governance V1

Status: IMPLEMENTED ON FEATURE BRANCH — merge only after Christiania quality gate passes.

## Purpose

This package makes the existing research machinery visible without weakening the scientific controls already present in the repository.

It does **not** create a second research architecture. It composes the existing command-deck read model, prospective evidence, model freeze, shadow pipeline, calibration-validity evidence and the repository-level edge-discovery artefacts into one operator surface.

The package also turns the previously declarative programme-family budget into a runtime-visible fail-closed gate.

## Operating doctrine

Christiania is a risk-selection machine, not a risk-avoidance machine. That does not permit statistical shortcuts.

The programme therefore keeps these ideas separate:

- collecting research observations;
- opening a new hypothesis family;
- using p-values or false-discovery procedures;
- promoting research into a trading decision.

Existing research may continue accumulating prospective evidence while the programme budget is `UNFROZEN`. What is blocked is opening or preregistering another edge family without an explicit programme allocation.

Academic evidence is treated as evidence that an effect existed in the studied sample, not proof that the effect remains tradable now.

## New runtime components

### `src/research/programme_family_governance_v1.py`

Reads:

- `research/edge_discovery/PROGRAMME_FAMILY_BUDGET_V1.json`;
- `research/edge_discovery/HYPOTHESIS_EVALUATION_LOG.jsonl`;
- the latest persisted `local_surface_calibration_validity_v1_runs` row when available.

It derives:

- programme-budget validity;
- allocated and actually opened family IDs;
- hypothesis-evaluation counts from the append-only log rather than a hand-entered total;
- remaining family capacity where a frozen maximum exists;
- whether another family may be activated;
- current calibration readiness;
- whether p-values, FDR or decision use are enabled.

Failure is closed. Missing or malformed governance artefacts do not become an empty budget.

### `src/dashboard/research_command_deck_v1.py`

Composes the existing `load_command_deck()` read model with programme-family governance.

The resulting operating states distinguish, among others:

- runtime not ready;
- research runtime degraded;
- governance failure;
- existing research collecting while new-family activation is blocked;
- family budget exhausted;
- discovery-only research;
- governed research active.

An unfrozen family budget therefore does **not** stop Christiania's already-running prospective calibration. It stops a new family from quietly entering the programme.

### `pages/01_Research_Command_Deck.py`

Adds a Streamlit Research Command Deck without replacing the existing application.

The page exposes:

- programme family-budget state;
- hypothesis-family usage;
- calibration/inference flags;
- daemon and market heartbeat;
- prospective evidence accumulation;
- research funnel counts;
- frozen model governance;
- prospective hypotheses;
- recent surfaced anomalies;
- recent shadow candidates;
- recent daemon iterations.

The page deliberately does not describe surfaced anomalies as validated edges or recommendations.

## Current expected state

`PROGRAMME_FAMILY_BUDGET_V1.json` remains deliberately `UNFROZEN` at the time this package is introduced.

Expected result:

- existing Christiania research continues collecting prospective evidence;
- new edge-family activation is blocked;
- p-values remain disabled;
- FDR remains disabled;
- decision use remains disabled;
- the Research Command Deck says this explicitly.

Freezing the next programme budget is a separate deliberate research-design action. It must not be smuggled into a UI or infrastructure release.

## Why this comes before the new Edge Library

The planned Edge Library introduces several plausible families: defined-risk variance risk premium, IV versus forecast realized volatility, demand pressure, idiosyncratic volatility, option momentum, variance seasonality and event-premium research.

Testing all of them without programme-level accounting would manufacture extra chances to discover noise. The family gate therefore lands before a second family is activated.

## Tests

`tests/test_programme_family_governance_v1.py` covers:

- unfrozen budget blocks new-family activation without stopping existing discovery;
- frozen preallocation permits only governed family space;
- an unallocated logged family fails closed;
- frozen-budget structural requirements;
- the repository's present budget remains deliberately unfrozen.

`tests/test_research_command_deck_v1.py` covers:

- existing research remains visible under an unfrozen programme budget;
- invalid governance fails closed;
- runtime failure takes priority over optimistic governance;
- degraded daemon evidence is not hidden.

The branch must pass the repository's standard GitHub Actions Christiania Quality Gate (`python .\\quality_gate.py --ci`) before merge.
