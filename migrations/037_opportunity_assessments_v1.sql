-- =====================================================================
-- Christiania — migration 037
--
-- Opportunity assessments and their resolved outcomes.
--
-- Purpose: make "does the score find better trades than chance?" a question
-- the database can answer with a prospective, timestamped record.
--
--   * Every proposed structure is assessed at creation time and the verdict,
--     score and ALL inputs are stored BEFORE the outcome exists. Skipped and
--     marginal ideas are stored too, not only the ones that look good.
--   * Every assessed idea gets a matched PLACEBO: the same butterfly shape on
--     the same snapshot at a randomly chosen centre strike, same direction.
--     If the score carries information, SIGNAL beats PLACEBO net of costs.
--   * Both kinds are resolved at expiry from the same stored terminal price.
--
-- Rows are append-only (UPDATE and DELETE abort). Outcomes use the same
-- terminal-price basis as shadow_expiry_outcomes_v1 and are NOT settlement
-- prices.
-- =====================================================================

PRAGMA foreign_keys = ON;

CREATE TABLE opportunity_assessments_v1 (
    id                  INTEGER PRIMARY KEY,
    proposal_id         INTEGER NOT NULL REFERENCES shadow_structure_proposals(id),
    kind                TEXT NOT NULL CHECK (kind IN ('SIGNAL', 'PLACEBO')),
    research_run_id     INTEGER NOT NULL REFERENCES research_runs(id),
    assessed_at         TEXT NOT NULL,
    scoring_version     TEXT NOT NULL,
    underlying          TEXT NOT NULL,
    expiration          TEXT NOT NULL,
    right               TEXT NOT NULL,
    structure_id        TEXT,
    target_strike       REAL NOT NULL,
    session_date        TEXT,
    verdict             TEXT NOT NULL,
    reason_code         TEXT NOT NULL,
    score               REAL,
    net_edge_usd        REAL,
    entry_cashflow_usd  REAL NOT NULL,
    fees_usd            REAL NOT NULL,
    max_loss_usd        REAL,
    legs_json           TEXT NOT NULL,
    features_json       TEXT NOT NULL,
    UNIQUE (proposal_id, kind)
);

CREATE INDEX idx_opportunity_assessments_expiry
    ON opportunity_assessments_v1 (expiration, underlying);

CREATE TABLE opportunity_outcomes_v1 (
    id                         INTEGER PRIMARY KEY,
    assessment_id              INTEGER NOT NULL UNIQUE
                               REFERENCES opportunity_assessments_v1(id),
    resolved_at                TEXT NOT NULL,
    research_run_id            INTEGER NOT NULL REFERENCES research_runs(id),
    snapshot_id                INTEGER NOT NULL REFERENCES market_snapshots(id),
    snapshot_captured_at       TEXT NOT NULL,
    terminal_underlying_price  REAL NOT NULL,
    terminal_value_usd         REAL NOT NULL,
    gross_pnl_usd              REAL NOT NULL,
    net_pnl_usd                REAL NOT NULL,
    settlement_basis           TEXT NOT NULL
                               DEFAULT 'LAST_STORED_EXPIRY_SESSION_UNDERLYING_SNAPSHOT'
);

CREATE TRIGGER trg_opportunity_assessments_no_update
BEFORE UPDATE ON opportunity_assessments_v1
BEGIN SELECT RAISE(ABORT, 'opportunity assessments are append-only'); END;

CREATE TRIGGER trg_opportunity_assessments_no_delete
BEFORE DELETE ON opportunity_assessments_v1
BEGIN SELECT RAISE(ABORT, 'opportunity assessments are append-only'); END;

CREATE TRIGGER trg_opportunity_outcomes_no_update
BEFORE UPDATE ON opportunity_outcomes_v1
BEGIN SELECT RAISE(ABORT, 'opportunity outcomes are append-only'); END;

CREATE TRIGGER trg_opportunity_outcomes_no_delete
BEFORE DELETE ON opportunity_outcomes_v1
BEGIN SELECT RAISE(ABORT, 'opportunity outcomes are append-only'); END;

INSERT INTO schema_version(version, applied_at)
SELECT 37, strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
WHERE NOT EXISTS (SELECT 1 FROM schema_version WHERE version = 37);
