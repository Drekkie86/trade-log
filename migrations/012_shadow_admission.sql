-- =====================================================================
-- Christiania — migration 012
--
-- Persist FX evidence and deterministic shadow-admission decisions.
--
-- Admission is research-only. It converts a bounded USD proposal to an EUR
-- risk reservation, applies an explicit shadow cost ceiling and the fixed
-- EUR 500 bankroll rule, then either BLOCKS or creates a shadow candidate.
-- =====================================================================

PRAGMA foreign_keys = ON;

CREATE TABLE fx_observations (
    id                          INTEGER PRIMARY KEY,
    provider                    TEXT    NOT NULL,
    base_currency               TEXT    NOT NULL,
    quote_currency              TEXT    NOT NULL,
    rate                        REAL    NOT NULL,
    reference_date              TEXT    NOT NULL,
    observed_at                 TEXT    NOT NULL,
    source_url                  TEXT,
    provenance                  TEXT    NOT NULL,

    CHECK (length(trim(provider)) > 0),
    CHECK (length(trim(base_currency)) = 3),
    CHECK (length(trim(quote_currency)) = 3),
    CHECK (base_currency != quote_currency),
    CHECK (rate > 0),
    CHECK (length(trim(provenance)) > 0)
);

CREATE INDEX idx_fx_observations_pair_date
ON fx_observations(
    base_currency,
    quote_currency,
    reference_date,
    observed_at
);

CREATE TRIGGER trg_fx_observations_no_update
BEFORE UPDATE ON fx_observations
BEGIN
    SELECT RAISE(
        ABORT,
        'FX observations are immutable evidence.'
    );
END;

CREATE TRIGGER trg_fx_observations_no_delete
BEFORE DELETE ON fx_observations
BEGIN
    SELECT RAISE(
        ABORT,
        'FX observations cannot be deleted.'
    );
END;


CREATE TABLE shadow_admission_decisions (
    id                          INTEGER PRIMARY KEY,
    proposal_id                 INTEGER NOT NULL
                                REFERENCES shadow_structure_proposals(id),
    fx_observation_id           INTEGER NOT NULL
                                REFERENCES fx_observations(id),
    candidate_id                INTEGER
                                REFERENCES shadow_candidates(id),

    sizing_policy_version       TEXT    NOT NULL,
    cost_model_version          TEXT    NOT NULL,
    cost_provenance             TEXT    NOT NULL,

    proposal_max_loss_usd_minor INTEGER NOT NULL,
    estimated_cost_usd_minor    INTEGER NOT NULL,
    reserved_risk_usd_minor     INTEGER NOT NULL,

    converted_max_loss_eur_minor INTEGER NOT NULL,
    estimated_cost_eur_minor    INTEGER NOT NULL,
    reserved_risk_eur_minor     INTEGER NOT NULL,
    bankroll_cap_eur_minor      INTEGER NOT NULL,

    decision                    TEXT    NOT NULL,
    reason_code                 TEXT    NOT NULL,
    decided_at                  TEXT    NOT NULL,
    evidence_json               TEXT    NOT NULL,

    UNIQUE (
        proposal_id,
        sizing_policy_version,
        cost_model_version
    ),

    CHECK (proposal_max_loss_usd_minor >= 0),
    CHECK (estimated_cost_usd_minor >= 0),
    CHECK (reserved_risk_usd_minor >= 0),
    CHECK (converted_max_loss_eur_minor >= 0),
    CHECK (estimated_cost_eur_minor >= 0),
    CHECK (reserved_risk_eur_minor >= 0),
    CHECK (bankroll_cap_eur_minor > 0),
    CHECK (decision IN ('ADMITTED', 'BLOCKED')),
    CHECK (
        (decision = 'ADMITTED' AND candidate_id IS NOT NULL)
        OR
        (decision = 'BLOCKED' AND candidate_id IS NULL)
    )
);

CREATE INDEX idx_shadow_admission_decisions_proposal
ON shadow_admission_decisions(proposal_id);

CREATE INDEX idx_shadow_admission_decisions_candidate
ON shadow_admission_decisions(candidate_id);

CREATE TRIGGER trg_shadow_admission_decisions_no_update
BEFORE UPDATE ON shadow_admission_decisions
BEGIN
    SELECT RAISE(
        ABORT,
        'Shadow admission decisions are immutable evidence.'
    );
END;

CREATE TRIGGER trg_shadow_admission_decisions_no_delete
BEFORE DELETE ON shadow_admission_decisions
BEGIN
    SELECT RAISE(
        ABORT,
        'Shadow admission decisions cannot be deleted.'
    );
END;

INSERT INTO schema_version (
    version,
    applied_at
)
SELECT
    12,
    strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
WHERE NOT EXISTS (
    SELECT 1
    FROM schema_version
    WHERE version = 12
);
