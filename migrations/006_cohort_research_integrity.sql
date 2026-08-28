-- =====================================================================
-- Christiania — migration 006
--
-- Cohort-001 research integrity hardening.
--
-- Adds:
--   * research run manifest and provider-attempt logging
--   * normalization-drop accounting
--   * frozen pre-resolution contract selections
--   * US session and OI/volume date semantics
--   * preregistration/code hashes on candidates
--   * quote-classifier version + independent quote-state flags
--   * observation gap separate from ingestion gap
--   * retry counts and resolution sequence
--   * provider-model input metadata
--
-- This migration is additive. Existing v4/v5 evidence remains intact.
-- =====================================================================

PRAGMA foreign_keys = ON;


-- =====================================================================
-- RESEARCH RUN MANIFEST
-- =====================================================================

CREATE TABLE research_runs (
    id                          INTEGER PRIMARY KEY,

    cohort_id                   TEXT    NOT NULL,
    preregistration_hash        TEXT    NOT NULL,
    code_git_sha                TEXT    NOT NULL,

    started_at                  TEXT    NOT NULL,
    ended_at                    TEXT,

    us_session_date             TEXT    NOT NULL,
    us_session_state            TEXT    NOT NULL,

    status                      TEXT    NOT NULL
                                DEFAULT 'STARTED',

    attempted_underlyings       INTEGER NOT NULL DEFAULT 0,
    succeeded_underlyings       INTEGER NOT NULL DEFAULT 0,
    failed_underlyings          INTEGER NOT NULL DEFAULT 0,

    provider_requests_attempted INTEGER NOT NULL DEFAULT 0,
    provider_requests_succeeded INTEGER NOT NULL DEFAULT 0,
    provider_requests_failed    INTEGER NOT NULL DEFAULT 0,

    massive_raw_contracts       INTEGER,
    massive_normalized_contracts INTEGER,
    normalization_drop_count    INTEGER,

    selected_strata_count       INTEGER,
    empty_strata_count          INTEGER,
    selected_contract_count     INTEGER,

    saxo_resolution_success_count INTEGER,
    saxo_resolution_failure_count INTEGER,

    underlying_observation_status TEXT,

    notes                       TEXT,

    CHECK (
        length(trim(cohort_id)) > 0
    ),

    CHECK (
        length(trim(preregistration_hash)) > 0
    ),

    CHECK (
        length(trim(code_git_sha)) > 0
    ),

    CHECK (
        us_session_state IN (
            'PRE_OPEN',
            'INTRADAY',
            'POST_CLOSE',
            'NON_TRADING_DAY'
        )
    ),

    CHECK (
        status IN (
            'STARTED',
            'COLLECTING',
            'COMPLETED',
            'FAILED',
            'INVALID'
        )
    ),

    CHECK (
        underlying_observation_status IS NULL
        OR underlying_observation_status IN (
            'SUCCESS',
            'FAILED',
            'NOT_ATTEMPTED'
        )
    ),

    CHECK (attempted_underlyings >= 0),
    CHECK (succeeded_underlyings >= 0),
    CHECK (failed_underlyings >= 0),

    CHECK (provider_requests_attempted >= 0),
    CHECK (provider_requests_succeeded >= 0),
    CHECK (provider_requests_failed >= 0),

    CHECK (
        massive_raw_contracts IS NULL
        OR massive_raw_contracts >= 0
    ),

    CHECK (
        massive_normalized_contracts IS NULL
        OR massive_normalized_contracts >= 0
    ),

    CHECK (
        normalization_drop_count IS NULL
        OR normalization_drop_count >= 0
    ),

    CHECK (
        selected_strata_count IS NULL
        OR selected_strata_count >= 0
    ),

    CHECK (
        empty_strata_count IS NULL
        OR empty_strata_count >= 0
    ),

    CHECK (
        selected_contract_count IS NULL
        OR selected_contract_count >= 0
    ),

    CHECK (
        saxo_resolution_success_count IS NULL
        OR saxo_resolution_success_count >= 0
    ),

    CHECK (
        saxo_resolution_failure_count IS NULL
        OR saxo_resolution_failure_count >= 0
    ),

    CHECK (
        ended_at IS NULL
        OR status IN (
            'COMPLETED',
            'FAILED',
            'INVALID'
        )
    ),

    CHECK (
        status NOT IN (
            'COMPLETED',
            'FAILED',
            'INVALID'
        )
        OR ended_at IS NOT NULL
    )
);


CREATE INDEX idx_research_runs_cohort
ON research_runs(cohort_id);

CREATE INDEX idx_research_runs_started_at
ON research_runs(started_at);

CREATE INDEX idx_research_runs_status
ON research_runs(status);


-- Once a run is terminal, its manifest is frozen.
CREATE TRIGGER trg_research_run_terminal_immutable
BEFORE UPDATE
ON research_runs
WHEN OLD.status IN (
    'COMPLETED',
    'FAILED',
    'INVALID'
)
BEGIN
    SELECT RAISE(
        ABORT,
        'Terminal research runs are immutable.'
    );
END;


CREATE TRIGGER trg_research_runs_no_delete
BEFORE DELETE
ON research_runs
BEGIN
    SELECT RAISE(
        ABORT,
        'Research runs cannot be deleted.'
    );
END;


-- =====================================================================
-- ATTEMPTED UNDERLYINGS
-- =====================================================================

CREATE TABLE research_run_underlyings (
    id              INTEGER PRIMARY KEY,

    run_id          INTEGER NOT NULL
                    REFERENCES research_runs(id),

    underlying      TEXT    NOT NULL,
    attempted_at    TEXT    NOT NULL,
    completed_at    TEXT,

    status          TEXT    NOT NULL,

    retry_count     INTEGER NOT NULL DEFAULT 0,

    failure_code    TEXT,
    failure_reason  TEXT,

    UNIQUE (
        run_id,
        underlying
    ),

    CHECK (
        length(trim(underlying)) > 0
    ),

    CHECK (
        status IN (
            'ATTEMPTED',
            'SUCCESS',
            'FAILED'
        )
    ),

    CHECK (
        retry_count >= 0
    ),

    CHECK (
        (
            status = 'FAILED'
            AND failure_reason IS NOT NULL
            AND length(trim(failure_reason)) > 0
        )
        OR
        (
            status <> 'FAILED'
            AND failure_reason IS NULL
        )
    )
);


CREATE INDEX idx_run_underlyings_run
ON research_run_underlyings(run_id);


-- =====================================================================
-- PROVIDER REQUEST ATTEMPTS
-- =====================================================================

CREATE TABLE research_provider_attempts (
    id              INTEGER PRIMARY KEY,

    run_id          INTEGER NOT NULL
                    REFERENCES research_runs(id),

    provider        TEXT    NOT NULL,
    operation       TEXT    NOT NULL,
    underlying      TEXT,

    attempted_at    TEXT    NOT NULL,
    completed_at    TEXT,

    succeeded       INTEGER NOT NULL,

    retry_count     INTEGER NOT NULL DEFAULT 0,

    request_id      TEXT,

    failure_code    TEXT,
    failure_reason  TEXT,

    CHECK (
        length(trim(provider)) > 0
    ),

    CHECK (
        length(trim(operation)) > 0
    ),

    CHECK (
        succeeded IN (0,1)
    ),

    CHECK (
        retry_count >= 0
    ),

    CHECK (
        (
            succeeded = 0
            AND failure_reason IS NOT NULL
            AND length(trim(failure_reason)) > 0
        )
        OR
        (
            succeeded = 1
            AND failure_reason IS NULL
        )
    )
);


CREATE INDEX idx_provider_attempts_run
ON research_provider_attempts(run_id);

CREATE INDEX idx_provider_attempts_provider
ON research_provider_attempts(provider);


CREATE TRIGGER trg_provider_attempts_no_update
BEFORE UPDATE
ON research_provider_attempts
BEGIN
    SELECT RAISE(
        ABORT,
        'Provider attempts are immutable evidence.'
    );
END;


CREATE TRIGGER trg_provider_attempts_no_delete
BEFORE DELETE
ON research_provider_attempts
BEGIN
    SELECT RAISE(
        ABORT,
        'Provider attempts cannot be deleted.'
    );
END;


-- =====================================================================
-- SNAPSHOT SESSION SEMANTICS
-- =====================================================================

ALTER TABLE market_snapshots
ADD COLUMN research_run_id INTEGER
REFERENCES research_runs(id);


ALTER TABLE market_snapshots
ADD COLUMN us_session_date TEXT;


ALTER TABLE market_snapshots
ADD COLUMN us_session_state TEXT
CHECK (
    us_session_state IS NULL
    OR us_session_state IN (
        'PRE_OPEN',
        'INTRADAY',
        'POST_CLOSE',
        'NON_TRADING_DAY'
    )
);


-- =====================================================================
-- OI / VOLUME EFFECTIVE-DATE SEMANTICS
-- =====================================================================

ALTER TABLE option_quotes
ADD COLUMN open_interest_as_of_date TEXT;


ALTER TABLE option_quotes
ADD COLUMN volume_trading_date TEXT;


-- =====================================================================
-- NORMALIZATION DROPS
--
-- Raw Massive contracts that fail normalization must be counted and
-- retained rather than silently disappearing before Saxo validation.
-- =====================================================================

CREATE TABLE normalization_drops (
    id                      INTEGER PRIMARY KEY,

    run_id                  INTEGER NOT NULL
                            REFERENCES research_runs(id),

    snapshot_id             INTEGER
                            REFERENCES market_snapshots(id),

    provider                TEXT    NOT NULL,
    underlying              TEXT    NOT NULL,

    provider_contract_id    TEXT,
    option_symbol           TEXT,

    raw_contract_type       TEXT,
    raw_strike              TEXT,
    raw_expiration          TEXT,

    reason_code             TEXT    NOT NULL,
    reason_detail           TEXT,

    dropped_at              TEXT    NOT NULL,

    raw_payload_json        TEXT,

    CHECK (
        reason_code IN (
            'UNSUPPORTED_CONTRACT_TYPE',
            'MISSING_STRIKE',
            'MISSING_EXPIRATION',
            'INVALID_STRIKE',
            'INVALID_EXPIRATION',
            'MISSING_CONTRACT_IDENTIFIER',
            'OTHER_NORMALIZATION_FAILURE'
        )
    ),

    CHECK (
        length(trim(provider)) > 0
    ),

    CHECK (
        length(trim(underlying)) > 0
    )
);


CREATE INDEX idx_normalization_drops_run
ON normalization_drops(run_id);

CREATE INDEX idx_normalization_drops_reason
ON normalization_drops(reason_code);


CREATE TRIGGER trg_normalization_drops_no_update
BEFORE UPDATE
ON normalization_drops
BEGIN
    SELECT RAISE(
        ABORT,
        'Normalization drops are immutable evidence.'
    );
END;


CREATE TRIGGER trg_normalization_drops_no_delete
BEFORE DELETE
ON normalization_drops
BEGIN
    SELECT RAISE(
        ABORT,
        'Normalization drops cannot be deleted.'
    );
END;


-- =====================================================================
-- FROZEN PRE-RESOLUTION SELECTIONS
--
-- Selection is stored before Saxo resolution. This prevents conditioning
-- the selected population on Saxo resolvability.
-- =====================================================================

CREATE TABLE research_selections (
    id                      INTEGER PRIMARY KEY,

    run_id                  INTEGER NOT NULL
                            REFERENCES research_runs(id),

    option_quote_id         INTEGER NOT NULL
                            REFERENCES option_quotes(id),

    selected_at             TEXT    NOT NULL,

    selection_rule          TEXT    NOT NULL,

    dte_stratum             TEXT    NOT NULL,
    delta_stratum           TEXT    NOT NULL,
    option_right            TEXT    NOT NULL,

    resolution_sequence     INTEGER NOT NULL,

    preregistration_hash    TEXT    NOT NULL,
    code_git_sha            TEXT    NOT NULL,

    UNIQUE (
        run_id,
        option_quote_id
    ),

    UNIQUE (
        run_id,
        resolution_sequence
    ),

    CHECK (
        option_right IN (
            'C',
            'P'
        )
    ),

    CHECK (
        resolution_sequence > 0
    ),

    CHECK (
        length(trim(selection_rule)) > 0
    ),

    CHECK (
        length(trim(preregistration_hash)) > 0
    ),

    CHECK (
        length(trim(code_git_sha)) > 0
    )
);


CREATE INDEX idx_research_selections_run
ON research_selections(run_id);

CREATE INDEX idx_research_selections_quote
ON research_selections(option_quote_id);


CREATE TRIGGER trg_selection_quote_belongs_to_run
BEFORE INSERT
ON research_selections
BEGIN
    SELECT CASE
        WHEN NOT EXISTS (
            SELECT 1
            FROM option_quotes AS oq
            JOIN market_snapshots AS ms
              ON ms.id = oq.snapshot_id
            WHERE oq.id = NEW.option_quote_id
              AND ms.research_run_id = NEW.run_id
        )
        THEN RAISE(
            ABORT,
            'Selected contract must belong to the research run snapshot.'
        )
    END;
END;


CREATE TRIGGER trg_research_selections_no_update
BEFORE UPDATE
ON research_selections
BEGIN
    SELECT RAISE(
        ABORT,
        'Research selections are immutable after selection.'
    );
END;


CREATE TRIGGER trg_research_selections_no_delete
BEFORE DELETE
ON research_selections
BEGIN
    SELECT RAISE(
        ABORT,
        'Research selections cannot be deleted.'
    );
END;


-- =====================================================================
-- CANDIDATE PREREGISTRATION PINNING
-- =====================================================================

ALTER TABLE candidates
ADD COLUMN preregistration_hash TEXT;


ALTER TABLE candidates
ADD COLUMN code_git_sha TEXT;


-- =====================================================================
-- PROVIDER MODEL REPRODUCIBILITY INPUTS
-- =====================================================================

ALTER TABLE provider_model_observations
ADD COLUMN model_underlying_price REAL
CHECK (
    model_underlying_price IS NULL
    OR model_underlying_price >= 0
);


ALTER TABLE provider_model_observations
ADD COLUMN model_rate REAL;


ALTER TABLE provider_model_observations
ADD COLUMN model_dividend_yield REAL;


ALTER TABLE provider_model_observations
ADD COLUMN model_input_notes TEXT;


-- =====================================================================
-- SAXO UNDERLYING QUOTE CLASSIFICATION
-- =====================================================================

ALTER TABLE saxo_underlying_observations
ADD COLUMN quote_quality_version TEXT NOT NULL
DEFAULT 'SAXO_QUOTE_CLASSIFIER_V1';


ALTER TABLE saxo_underlying_observations
ADD COLUMN is_stale INTEGER NOT NULL DEFAULT 0
CHECK (is_stale IN (0,1));


ALTER TABLE saxo_underlying_observations
ADD COLUMN is_indicative INTEGER NOT NULL DEFAULT 0
CHECK (is_indicative IN (0,1));


ALTER TABLE saxo_underlying_observations
ADD COLUMN is_delayed INTEGER NOT NULL DEFAULT 0
CHECK (is_delayed IN (0,1));


ALTER TABLE saxo_underlying_observations
ADD COLUMN is_locked INTEGER NOT NULL DEFAULT 0
CHECK (is_locked IN (0,1));


ALTER TABLE saxo_underlying_observations
ADD COLUMN is_crossed INTEGER NOT NULL DEFAULT 0
CHECK (is_crossed IN (0,1));


ALTER TABLE saxo_underlying_observations
ADD COLUMN observation_gap_seconds REAL
CHECK (
    observation_gap_seconds IS NULL
    OR observation_gap_seconds >= 0
);


ALTER TABLE saxo_underlying_observations
ADD COLUMN retry_count INTEGER NOT NULL DEFAULT 0
CHECK (retry_count >= 0);


-- =====================================================================
-- SAXO OPTION QUOTE CLASSIFICATION / RESOLUTION ORDER
-- =====================================================================

ALTER TABLE saxo_option_observations
ADD COLUMN quote_quality_version TEXT NOT NULL
DEFAULT 'SAXO_QUOTE_CLASSIFIER_V1';


ALTER TABLE saxo_option_observations
ADD COLUMN is_stale INTEGER NOT NULL DEFAULT 0
CHECK (is_stale IN (0,1));


ALTER TABLE saxo_option_observations
ADD COLUMN is_indicative INTEGER NOT NULL DEFAULT 0
CHECK (is_indicative IN (0,1));


ALTER TABLE saxo_option_observations
ADD COLUMN is_delayed INTEGER NOT NULL DEFAULT 0
CHECK (is_delayed IN (0,1));


ALTER TABLE saxo_option_observations
ADD COLUMN is_locked INTEGER NOT NULL DEFAULT 0
CHECK (is_locked IN (0,1));


ALTER TABLE saxo_option_observations
ADD COLUMN is_crossed INTEGER NOT NULL DEFAULT 0
CHECK (is_crossed IN (0,1));


ALTER TABLE saxo_option_observations
ADD COLUMN observation_gap_seconds REAL
CHECK (
    observation_gap_seconds IS NULL
    OR observation_gap_seconds >= 0
);


ALTER TABLE saxo_option_observations
ADD COLUMN retry_count INTEGER NOT NULL DEFAULT 0
CHECK (retry_count >= 0);


ALTER TABLE saxo_option_observations
ADD COLUMN resolution_sequence INTEGER
CHECK (
    resolution_sequence IS NULL
    OR resolution_sequence > 0
);


-- =====================================================================
-- RESOLUTION FAILURES: RETRIES + RANDOMIZED SEQUENCE
-- =====================================================================

ALTER TABLE saxo_resolution_failures
ADD COLUMN retry_count INTEGER NOT NULL DEFAULT 0
CHECK (retry_count >= 0);


ALTER TABLE saxo_resolution_failures
ADD COLUMN resolution_sequence INTEGER
CHECK (
    resolution_sequence IS NULL
    OR resolution_sequence > 0
);


-- =====================================================================
-- V6 RESEARCH INTEGRITY VIEW
-- =====================================================================

CREATE VIEW v_research_run_reconciliation AS
SELECT
    rr.id AS run_id,
    rr.cohort_id,
    rr.status,

    rr.massive_raw_contracts,
    rr.massive_normalized_contracts,
    rr.normalization_drop_count,

    CASE
        WHEN
            rr.massive_raw_contracts IS NULL
            OR rr.massive_normalized_contracts IS NULL
            OR rr.normalization_drop_count IS NULL
        THEN NULL

        WHEN
            rr.massive_raw_contracts
            =
            rr.massive_normalized_contracts
            + rr.normalization_drop_count
        THEN 1

        ELSE 0
    END AS normalization_reconciles,

    rr.selected_contract_count,
    rr.saxo_resolution_success_count,
    rr.saxo_resolution_failure_count,

    CASE
        WHEN
            rr.selected_contract_count IS NULL
            OR rr.saxo_resolution_success_count IS NULL
            OR rr.saxo_resolution_failure_count IS NULL
        THEN NULL

        WHEN
            rr.selected_contract_count
            =
            rr.saxo_resolution_success_count
            + rr.saxo_resolution_failure_count
        THEN 1

        ELSE 0
    END AS resolution_reconciles

FROM research_runs AS rr;


-- =====================================================================
-- VERSION
-- =====================================================================

INSERT INTO schema_version (
    version,
    applied_at
)
VALUES (
    6,
    strftime(
        '%Y-%m-%dT%H:%M:%SZ',
        'now'
    )
);
