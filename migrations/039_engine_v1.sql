-- Christiania schema v39: the single trade engine.
-- Scans, the candidates each scan surfaced, every recommended pick (frozen at
-- first appearance), daily closes for the models, and settled outcomes.
-- Additive only: no existing table is touched.

PRAGMA foreign_keys = ON;

CREATE TABLE engine_scans (
    id INTEGER PRIMARY KEY,
    lane TEXT NOT NULL CHECK (lane IN ('MAIN','ZERO_DTE')),
    asof_at TEXT NOT NULL,
    completed_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('COMPLETED','FAILED')),
    engine_version TEXT NOT NULL,
    config_json TEXT NOT NULL CHECK (json_valid(config_json)),
    chains_scanned INTEGER NOT NULL DEFAULT 0 CHECK (chains_scanned >= 0),
    structures_scored INTEGER NOT NULL DEFAULT 0 CHECK (structures_scored >= 0),
    passed_count INTEGER NOT NULL DEFAULT 0 CHECK (passed_count >= 0),
    rejections_json TEXT NOT NULL CHECK (json_valid(rejections_json)),
    chains_without_history_json TEXT NOT NULL
        CHECK (json_valid(chains_without_history_json)),
    error_message TEXT
);
CREATE INDEX idx_engine_scans_lane ON engine_scans (lane, id);

CREATE TABLE engine_candidates (
    id INTEGER PRIMARY KEY,
    scan_id INTEGER NOT NULL REFERENCES engine_scans(id),
    kind TEXT NOT NULL CHECK (kind IN ('PASSED','NEAR_MISS')),
    rank INTEGER NOT NULL CHECK (rank >= 1),
    underlying TEXT NOT NULL,
    expiration TEXT NOT NULL,
    family TEXT NOT NULL,
    structure_key TEXT NOT NULL,
    record_json TEXT NOT NULL CHECK (json_valid(record_json)),
    UNIQUE (scan_id, kind, rank)
);

CREATE TABLE engine_picks (
    id INTEGER PRIMARY KEY,
    lane TEXT NOT NULL CHECK (lane IN ('MAIN','ZERO_DTE')),
    session_date TEXT NOT NULL,
    underlying TEXT NOT NULL,
    expiration TEXT NOT NULL,
    family TEXT NOT NULL,
    shape TEXT NOT NULL,
    structure_key TEXT NOT NULL,
    first_scan_id INTEGER NOT NULL REFERENCES engine_scans(id),
    first_seen_at TEXT NOT NULL,
    entry_cash_usd REAL NOT NULL,
    max_loss_usd REAL NOT NULL CHECK (max_loss_usd > 0),
    conservative_ev_usd REAL NOT NULL,
    record_json TEXT NOT NULL CHECK (json_valid(record_json)),
    UNIQUE (lane, session_date, structure_key)
);
CREATE INDEX idx_engine_picks_expiration ON engine_picks (expiration);

CREATE TABLE engine_pick_outcomes (
    pick_id INTEGER PRIMARY KEY REFERENCES engine_picks(id),
    settled_at TEXT NOT NULL,
    settlement_date TEXT NOT NULL,
    settlement_price REAL NOT NULL CHECK (settlement_price > 0),
    settlement_source TEXT NOT NULL
        CHECK (settlement_source IN ('THETADATA_EOD','SNAPSHOT_NEAR_CLOSE')),
    pnl_usd REAL NOT NULL
);

CREATE TABLE engine_daily_closes (
    symbol TEXT NOT NULL,
    session_date TEXT NOT NULL,
    close REAL NOT NULL CHECK (close > 0),
    source TEXT NOT NULL CHECK (source = 'THETADATA_EOD'),
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (symbol, session_date)
);

CREATE TRIGGER trg_engine_scans_no_update BEFORE UPDATE ON engine_scans
BEGIN SELECT RAISE(ABORT,'engine scans are immutable'); END;
CREATE TRIGGER trg_engine_candidates_no_update BEFORE UPDATE ON engine_candidates
BEGIN SELECT RAISE(ABORT,'engine candidates are immutable'); END;
CREATE TRIGGER trg_engine_picks_no_update BEFORE UPDATE ON engine_picks
BEGIN SELECT RAISE(ABORT,'engine picks are immutable'); END;
CREATE TRIGGER trg_engine_picks_no_delete BEFORE DELETE ON engine_picks
BEGIN SELECT RAISE(ABORT,'engine picks are immutable'); END;
CREATE TRIGGER trg_engine_outcomes_no_update BEFORE UPDATE ON engine_pick_outcomes
BEGIN SELECT RAISE(ABORT,'engine outcomes are immutable'); END;
CREATE TRIGGER trg_engine_outcomes_no_delete BEFORE DELETE ON engine_pick_outcomes
BEGIN SELECT RAISE(ABORT,'engine outcomes are immutable'); END;

INSERT INTO schema_version(version, applied_at)
SELECT 39, strftime('%Y-%m-%dT%H:%M:%SZ','now')
WHERE NOT EXISTS (SELECT 1 FROM schema_version WHERE version=39);
