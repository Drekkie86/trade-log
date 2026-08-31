-- =====================================================================
-- Christiania — migration 013
--
-- Repeated research daemon operations + longitudinal shadow marks.
--
-- This migration deliberately distinguishes:
--   1. operational daemon state/iterations, and
--   2. immutable research evidence.
--
-- The daemon lock is mutable operational state.
-- Iteration records and shadow marks are append-only evidence.
-- =====================================================================

PRAGMA foreign_keys = ON;

CREATE TABLE research_daemon_lock (
    singleton_id                INTEGER PRIMARY KEY
                                CHECK (singleton_id = 1),
    owner_token                 TEXT    NOT NULL,
    acquired_at                 TEXT    NOT NULL,
    heartbeat_at                TEXT    NOT NULL,
    CHECK (length(trim(owner_token)) > 0)
);


CREATE TABLE research_daemon_iterations (
    id                          INTEGER PRIMARY KEY,
    owner_token                 TEXT    NOT NULL,
    scheduled_for               TEXT    NOT NULL,
    started_at                  TEXT    NOT NULL,
    completed_at                TEXT,
    status                      TEXT    NOT NULL,
    research_run_id             INTEGER
                                REFERENCES research_runs(id),
    hypothesis_scanner_run_id   INTEGER
                                REFERENCES hypothesis_scanner_runs(id),
    proposals_count             INTEGER,
    admitted_count              INTEGER,
    blocked_count               INTEGER,
    outcome_mark_count          INTEGER,
    error_type                  TEXT,
    error_message               TEXT,
    evidence_json               TEXT,

    CHECK (
        status IN (
            'RUNNING',
            'COMPLETED',
            'FAILED'
        )
    ),
    CHECK (
        proposals_count IS NULL
        OR proposals_count >= 0
    ),
    CHECK (
        admitted_count IS NULL
        OR admitted_count >= 0
    ),
    CHECK (
        blocked_count IS NULL
        OR blocked_count >= 0
    ),
    CHECK (
        outcome_mark_count IS NULL
        OR outcome_mark_count >= 0
    )
);

CREATE INDEX idx_research_daemon_iterations_schedule
ON research_daemon_iterations(
    scheduled_for,
    id
);

CREATE INDEX idx_research_daemon_iterations_run
ON research_daemon_iterations(
    research_run_id
);

CREATE TRIGGER trg_research_daemon_iterations_no_delete
BEFORE DELETE ON research_daemon_iterations
BEGIN
    SELECT RAISE(
        ABORT,
        'Research daemon iteration history cannot be deleted.'
    );
END;


CREATE TABLE shadow_mark_observations (
    id                          INTEGER PRIMARY KEY,
    candidate_id                INTEGER NOT NULL
                                REFERENCES shadow_candidates(id),
    research_run_id             INTEGER NOT NULL
                                REFERENCES research_runs(id),
    observed_at                 TEXT    NOT NULL,
    provider                    TEXT    NOT NULL,

    structure_mark_usd_minor    INTEGER,
    gross_pnl_usd_minor         INTEGER,
    estimated_net_pnl_usd_minor INTEGER,
    gross_pnl_eur_minor         INTEGER,
    estimated_net_pnl_eur_minor INTEGER,

    entry_fx_observation_id     INTEGER
                                REFERENCES fx_observations(id),
    quality_state               TEXT    NOT NULL,
    evidence_json               TEXT    NOT NULL,

    UNIQUE (
        candidate_id,
        research_run_id
    ),

    CHECK (length(trim(provider)) > 0),
    CHECK (
        quality_state IN (
            'COMPLETE_UNVERIFIED_FRESHNESS',
            'INCOMPLETE_LEG_MARK',
            'INVALID_MARK'
        )
    )
);

CREATE INDEX idx_shadow_mark_candidate_time
ON shadow_mark_observations(
    candidate_id,
    observed_at,
    id
);

CREATE INDEX idx_shadow_mark_research_run
ON shadow_mark_observations(
    research_run_id
);

CREATE TRIGGER trg_shadow_mark_observations_no_update
BEFORE UPDATE ON shadow_mark_observations
BEGIN
    SELECT RAISE(
        ABORT,
        'Shadow mark observations are immutable evidence.'
    );
END;

CREATE TRIGGER trg_shadow_mark_observations_no_delete
BEFORE DELETE ON shadow_mark_observations
BEGIN
    SELECT RAISE(
        ABORT,
        'Shadow mark observations cannot be deleted.'
    );
END;


INSERT INTO schema_version (
    version,
    applied_at
)
SELECT
    13,
    strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
WHERE NOT EXISTS (
    SELECT 1
    FROM schema_version
    WHERE version = 13
);
