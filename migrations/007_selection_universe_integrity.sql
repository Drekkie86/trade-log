-- =====================================================================
-- Christiania — migration 007
--
-- Cohort 001 selection-universe integrity.
--
-- Purpose:
--   * no normalized contract may silently disappear before stratification
--   * persist selection-stage exclusions
--   * reconcile normalized = selection-eligible + selection-excluded
--   * support preregistration v2 / sampling rule v2
-- =====================================================================

PRAGMA foreign_keys = ON;

ALTER TABLE research_runs
ADD COLUMN selection_eligible_count INTEGER
CHECK (
    selection_eligible_count IS NULL
    OR selection_eligible_count >= 0
);

ALTER TABLE research_runs
ADD COLUMN selection_exclusion_count INTEGER
CHECK (
    selection_exclusion_count IS NULL
    OR selection_exclusion_count >= 0
);

CREATE TABLE selection_exclusions (
    id                      INTEGER PRIMARY KEY,

    run_id                  INTEGER NOT NULL
                            REFERENCES research_runs(id),

    snapshot_id             INTEGER
                            REFERENCES market_snapshots(id),

    option_quote_id         INTEGER NOT NULL
                            REFERENCES option_quotes(id),

    provider                TEXT    NOT NULL,
    underlying              TEXT    NOT NULL,

    provider_contract_id    TEXT,
    option_symbol           TEXT,

    option_right            TEXT,
    strike                  REAL,
    expiration              TEXT,

    reason_code             TEXT    NOT NULL,
    reason_detail           TEXT,

    excluded_at             TEXT    NOT NULL,

    preregistration_hash    TEXT    NOT NULL,
    code_git_sha            TEXT    NOT NULL,

    UNIQUE (
        run_id,
        option_quote_id
    ),

    CHECK (
        reason_code IN (
            'MISSING_DELTA',
            'OUTSIDE_DELTA_SAMPLING_RANGE',
            'NO_SYMBOL',
            'NO_MATCHING_MODEL_OBSERVATION',
            'DUPLICATE_MODEL_OBSERVATION',
            'INVALID_DELTA',
            'OTHER_SELECTION_INTEGRITY_FAILURE'
        )
    ),

    CHECK (
        option_right IS NULL
        OR option_right IN ('C', 'P')
    ),

    CHECK (
        strike IS NULL
        OR strike >= 0
    ),

    CHECK (length(trim(provider)) > 0),
    CHECK (length(trim(underlying)) > 0),
    CHECK (length(trim(preregistration_hash)) > 0),
    CHECK (length(trim(code_git_sha)) > 0)
);

CREATE INDEX idx_selection_exclusions_run
ON selection_exclusions(run_id);

CREATE INDEX idx_selection_exclusions_quote
ON selection_exclusions(option_quote_id);

CREATE INDEX idx_selection_exclusions_reason
ON selection_exclusions(reason_code);

CREATE TRIGGER trg_selection_exclusion_quote_belongs_to_run
BEFORE INSERT
ON selection_exclusions
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
            'Selection exclusion must belong to the research run snapshot.'
        )
    END;
END;


CREATE TRIGGER trg_selection_exclusions_no_update
BEFORE UPDATE
ON selection_exclusions
BEGIN
    SELECT RAISE(
        ABORT,
        'Selection exclusions are immutable evidence.'
    );
END;

CREATE TRIGGER trg_selection_exclusions_no_delete
BEFORE DELETE
ON selection_exclusions
BEGIN
    SELECT RAISE(
        ABORT,
        'Selection exclusions cannot be deleted.'
    );
END;

CREATE VIEW v_selection_universe_reconciliation AS
SELECT
    rr.id AS run_id,
    rr.cohort_id,
    rr.massive_normalized_contracts,
    rr.selection_eligible_count,
    rr.selection_exclusion_count,

    (
        SELECT COUNT(*)
        FROM selection_exclusions AS se
        WHERE se.run_id = rr.id
    ) AS actual_selection_exclusion_rows,

    CASE
        WHEN rr.massive_normalized_contracts IS NULL
          OR rr.selection_eligible_count IS NULL
          OR rr.selection_exclusion_count IS NULL
        THEN NULL

        WHEN rr.massive_normalized_contracts
             =
             rr.selection_eligible_count
             + rr.selection_exclusion_count
        THEN 1

        ELSE 0
    END AS selection_population_reconciles

FROM research_runs AS rr;

INSERT INTO schema_version (
    version,
    applied_at
)
SELECT
    7,
    strftime(
        '%Y-%m-%dT%H:%M:%SZ',
        'now'
    )
WHERE NOT EXISTS (
    SELECT 1
    FROM schema_version
    WHERE version = 7
);
