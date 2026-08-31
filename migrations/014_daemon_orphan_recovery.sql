-- =====================================================================
-- Christiania — migration 014
--
-- Hostile-review hardening:
-- allow stale daemon iterations to be terminally classified as ORPHANED.
--
-- Migration 013 is intentionally left unchanged. This migration rebuilds
-- research_daemon_iterations so already-migrated real databases and fresh
-- builds converge on the same schema.
-- =====================================================================

PRAGMA foreign_keys = ON;

CREATE TABLE research_daemon_iterations_v14 (
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
            'FAILED',
            'ORPHANED'
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

INSERT INTO research_daemon_iterations_v14 (
    id,
    owner_token,
    scheduled_for,
    started_at,
    completed_at,
    status,
    research_run_id,
    hypothesis_scanner_run_id,
    proposals_count,
    admitted_count,
    blocked_count,
    outcome_mark_count,
    error_type,
    error_message,
    evidence_json
)
SELECT
    id,
    owner_token,
    scheduled_for,
    started_at,
    completed_at,
    status,
    research_run_id,
    hypothesis_scanner_run_id,
    proposals_count,
    admitted_count,
    blocked_count,
    outcome_mark_count,
    error_type,
    error_message,
    evidence_json
FROM research_daemon_iterations;

DROP TRIGGER IF EXISTS trg_research_daemon_iterations_no_delete;
DROP INDEX IF EXISTS idx_research_daemon_iterations_schedule;
DROP INDEX IF EXISTS idx_research_daemon_iterations_run;

DROP TABLE research_daemon_iterations;

ALTER TABLE research_daemon_iterations_v14
RENAME TO research_daemon_iterations;

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

INSERT INTO schema_version (
    version,
    applied_at
)
SELECT
    14,
    strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
WHERE NOT EXISTS (
    SELECT 1
    FROM schema_version
    WHERE version = 14
);
