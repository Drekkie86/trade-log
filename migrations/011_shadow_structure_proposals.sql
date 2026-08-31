-- =====================================================================
-- Christiania — migration 011
--
-- Persist defined-risk shadow structure proposals derived from surfaced
-- hypothesis observations.
--
-- A proposal is NOT a shadow candidate. It is an immutable bridge object
-- that records whether a surfaced empirical anomaly can be expressed as a
-- bounded-loss multi-leg structure using the frozen builder rules.
-- =====================================================================

PRAGMA foreign_keys = ON;

CREATE TABLE shadow_structure_proposals (
    id                          INTEGER PRIMARY KEY,
    hypothesis_evaluation_id    INTEGER NOT NULL
                                REFERENCES hypothesis_scanner_evaluations(id),
    research_run_id             INTEGER NOT NULL
                                REFERENCES research_runs(id),
    target_reference_contract_id INTEGER NOT NULL
                                REFERENCES listing_reference_contracts(id),
    underlying                  TEXT    NOT NULL,
    expiration                  TEXT    NOT NULL,
    right                       TEXT    NOT NULL,
    target_strike               REAL    NOT NULL,

    builder_family_id           TEXT    NOT NULL,
    builder_version             TEXT    NOT NULL,
    builder_rule_version        TEXT    NOT NULL,

    anomaly_direction           TEXT    NOT NULL,
    proposal_state              TEXT    NOT NULL,
    reason_code                 TEXT    NOT NULL,

    structure_id                TEXT,
    structure_version           TEXT,
    structure_json              TEXT,

    entry_pricing_json          TEXT,
    risk_currency               TEXT,
    max_theoretical_loss_minor  INTEGER,
    risk_basis                  TEXT,

    created_at                  TEXT    NOT NULL,

    UNIQUE (
        hypothesis_evaluation_id,
        builder_family_id,
        builder_version
    ),

    CHECK (length(trim(underlying)) > 0),
    CHECK (right IN ('C', 'P')),
    CHECK (target_strike >= 0),
    CHECK (
        anomaly_direction IN (
            'IV_RICH_LOCAL',
            'IV_CHEAP_LOCAL'
        )
    ),
    CHECK (
        proposal_state IN (
            'PROPOSED',
            'BLOCKED'
        )
    ),
    CHECK (
        risk_currency IS NULL
        OR length(trim(risk_currency)) = 3
    ),
    CHECK (
        max_theoretical_loss_minor IS NULL
        OR max_theoretical_loss_minor >= 0
    ),
    CHECK (
        proposal_state = 'BLOCKED'
        OR (
            structure_id IS NOT NULL
            AND structure_version IS NOT NULL
            AND structure_json IS NOT NULL
            AND entry_pricing_json IS NOT NULL
            AND risk_currency IS NOT NULL
            AND max_theoretical_loss_minor IS NOT NULL
            AND risk_basis IS NOT NULL
        )
    )
);

CREATE INDEX idx_shadow_structure_proposals_run
ON shadow_structure_proposals(
    research_run_id,
    proposal_state
);

CREATE INDEX idx_shadow_structure_proposals_target
ON shadow_structure_proposals(
    target_reference_contract_id
);

CREATE TRIGGER trg_shadow_structure_proposals_no_update
BEFORE UPDATE ON shadow_structure_proposals
BEGIN
    SELECT RAISE(
        ABORT,
        'Shadow structure proposals are immutable evidence.'
    );
END;

CREATE TRIGGER trg_shadow_structure_proposals_no_delete
BEFORE DELETE ON shadow_structure_proposals
BEGIN
    SELECT RAISE(
        ABORT,
        'Shadow structure proposals cannot be deleted.'
    );
END;

INSERT INTO schema_version (
    version,
    applied_at
)
SELECT
    11,
    strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
WHERE NOT EXISTS (
    SELECT 1
    FROM schema_version
    WHERE version = 11
);
