-- =====================================================================
-- Christiania — migration 010
--
-- Persist deterministic hypothesis-scanner evaluations.
--
-- This preserves the full selection surface, not only surfaced findings.
-- =====================================================================

PRAGMA foreign_keys = ON;

CREATE TABLE hypothesis_scanner_runs (
    id                          INTEGER PRIMARY KEY,
    research_run_id             INTEGER NOT NULL
                                REFERENCES research_runs(id),
    scanner_family_id           TEXT    NOT NULL,
    scanner_version             TEXT    NOT NULL,
    rule_version                TEXT    NOT NULL,
    hypothesis_family           TEXT    NOT NULL,
    hypothesis_version          TEXT    NOT NULL,
    config_hash                 TEXT    NOT NULL,
    config_json                 TEXT    NOT NULL,
    evaluated_at                TEXT    NOT NULL,
    structural_input_count      INTEGER NOT NULL,
    evaluable_count             INTEGER NOT NULL,
    surfaced_count              INTEGER NOT NULL,

    CHECK (length(trim(scanner_family_id)) > 0),
    CHECK (length(trim(scanner_version)) > 0),
    CHECK (length(trim(rule_version)) > 0),
    CHECK (length(trim(hypothesis_family)) > 0),
    CHECK (length(trim(hypothesis_version)) > 0),
    CHECK (length(config_hash) = 64),
    CHECK (structural_input_count >= 0),
    CHECK (evaluable_count >= 0),
    CHECK (surfaced_count >= 0),
    CHECK (evaluable_count <= structural_input_count),
    CHECK (surfaced_count <= evaluable_count)
);

CREATE INDEX idx_hypothesis_scanner_runs_research
ON hypothesis_scanner_runs(
    research_run_id,
    scanner_family_id,
    scanner_version
);

CREATE TABLE hypothesis_scanner_evaluations (
    id                          INTEGER PRIMARY KEY,
    scanner_run_id              INTEGER NOT NULL
                                REFERENCES hypothesis_scanner_runs(id),
    reference_contract_id       INTEGER NOT NULL
                                REFERENCES listing_reference_contracts(id),
    option_quote_id             INTEGER NOT NULL
                                REFERENCES option_quotes(id),
    underlying                  TEXT    NOT NULL,
    expiration                  TEXT    NOT NULL,
    strike                      REAL    NOT NULL,
    right                       TEXT    NOT NULL,
    delta                       REAL,
    implied_volatility          REAL,
    lower_strike                REAL,
    lower_iv                    REAL,
    upper_strike                REAL,
    upper_iv                    REAL,
    interpolated_iv             REAL,
    iv_residual                 REAL,
    abs_iv_residual             REAL,
    residual_threshold          REAL    NOT NULL,
    evaluation_state            TEXT    NOT NULL,
    reason_code                 TEXT    NOT NULL,
    surfaced_direction          TEXT,
    evidence_json               TEXT    NOT NULL,

    CHECK (right IN ('C', 'P')),
    CHECK (residual_threshold > 0),
    CHECK (
        evaluation_state IN (
            'NOT_EVALUABLE',
            'EVALUATED_NOT_SURFACED',
            'SURFACED'
        )
    ),
    CHECK (
        surfaced_direction IS NULL
        OR surfaced_direction IN (
            'IV_RICH_LOCAL',
            'IV_CHEAP_LOCAL'
        )
    ),
    CHECK (
        evaluation_state = 'SURFACED'
        OR surfaced_direction IS NULL
    )
);

CREATE UNIQUE INDEX uq_hypothesis_scanner_evaluation_quote
ON hypothesis_scanner_evaluations(
    scanner_run_id,
    option_quote_id
);

CREATE INDEX idx_hypothesis_scanner_evaluations_surface
ON hypothesis_scanner_evaluations(
    scanner_run_id,
    evaluation_state,
    underlying,
    expiration
);

CREATE TRIGGER trg_hypothesis_scanner_runs_no_update
BEFORE UPDATE ON hypothesis_scanner_runs
BEGIN
    SELECT RAISE(
        ABORT,
        'Hypothesis scanner runs are immutable evidence.'
    );
END;

CREATE TRIGGER trg_hypothesis_scanner_runs_no_delete
BEFORE DELETE ON hypothesis_scanner_runs
BEGIN
    SELECT RAISE(
        ABORT,
        'Hypothesis scanner runs cannot be deleted.'
    );
END;

CREATE TRIGGER trg_hypothesis_scanner_evaluations_no_update
BEFORE UPDATE ON hypothesis_scanner_evaluations
BEGIN
    SELECT RAISE(
        ABORT,
        'Hypothesis scanner evaluations are immutable evidence.'
    );
END;

CREATE TRIGGER trg_hypothesis_scanner_evaluations_no_delete
BEFORE DELETE ON hypothesis_scanner_evaluations
BEGIN
    SELECT RAISE(
        ABORT,
        'Hypothesis scanner evaluations cannot be deleted.'
    );
END;

INSERT INTO schema_version (
    version,
    applied_at
)
SELECT
    10,
    strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
WHERE NOT EXISTS (
    SELECT 1
    FROM schema_version
    WHERE version = 10
);
