-- Christiania schema v39: the single trade engine.
-- Scans, the candidates each scan surfaced, one frozen pick per underlying per
-- session (decision scan only), daily closes and intraday bars for the models,
-- settled outcomes, and the real trades the operator records against them.
-- Additive only: no existing table is touched.

PRAGMA foreign_keys = ON;

CREATE TABLE engine_scans (
    id INTEGER PRIMARY KEY,
    lane TEXT NOT NULL CHECK (lane IN ('MAIN','ZERO_DTE')),
    session_date TEXT NOT NULL,
    asof_at TEXT NOT NULL,
    completed_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('COMPLETED','FAILED')),
    decision INTEGER NOT NULL DEFAULT 0 CHECK (decision IN (0,1)),
    engine_version TEXT NOT NULL,
    config_json TEXT NOT NULL CHECK (json_valid(config_json)),
    chains_scanned INTEGER NOT NULL DEFAULT 0 CHECK (chains_scanned >= 0),
    structures_scored INTEGER NOT NULL DEFAULT 0 CHECK (structures_scored >= 0),
    passed_count INTEGER NOT NULL DEFAULT 0 CHECK (passed_count >= 0),
    rejections_json TEXT NOT NULL CHECK (json_valid(rejections_json)),
    chains_without_history_json TEXT NOT NULL
        CHECK (json_valid(chains_without_history_json)),
    chains_blocked_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(chains_blocked_json)),
    error_message TEXT
);
CREATE INDEX idx_engine_scans_lane ON engine_scans (lane, id);
CREATE INDEX idx_engine_scans_decision ON engine_scans (lane, session_date, decision);

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
CREATE INDEX idx_engine_candidates_scan ON engine_candidates (scan_id);

-- One frozen pick per underlying per session, from the session's decision scan.
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
    UNIQUE (lane, session_date, underlying)
);
CREATE INDEX idx_engine_picks_expiration ON engine_picks (expiration);

CREATE TABLE engine_pick_outcomes (
    pick_id INTEGER PRIMARY KEY REFERENCES engine_picks(id),
    settled_at TEXT NOT NULL,
    settlement_date TEXT NOT NULL,
    settlement_price REAL NOT NULL CHECK (settlement_price > 0),
    settlement_source TEXT NOT NULL CHECK (settlement_source IN ('THETADATA_EOD')),
    settlement_after_hours INTEGER NOT NULL DEFAULT 0 CHECK (settlement_after_hours IN (0,1)),
    near_strike INTEGER NOT NULL DEFAULT 0 CHECK (near_strike IN (0,1)),
    pnl_usd REAL NOT NULL
);

CREATE TABLE engine_daily_closes (
    symbol TEXT NOT NULL,
    session_date TEXT NOT NULL,
    close REAL NOT NULL CHECK (close > 0),
    source TEXT NOT NULL CHECK (source = 'THETADATA_EOD'),
    fetched_at TEXT NOT NULL,
    last_trade_at TEXT,
    after_hours INTEGER NOT NULL DEFAULT 0 CHECK (after_hours IN (0,1)),
    PRIMARY KEY (symbol, session_date)
);

CREATE TABLE engine_intraday_sessions (
    symbol TEXT NOT NULL,
    session_date TEXT NOT NULL,
    bars_json TEXT NOT NULL CHECK (json_valid(bars_json)),
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (symbol, session_date)
);

-- Real trades the operator took, recorded against a candidate; immutable.
CREATE TABLE engine_trades (
    id INTEGER PRIMARY KEY,
    pick_id INTEGER REFERENCES engine_picks(id),
    taken_at TEXT NOT NULL,
    lane TEXT NOT NULL CHECK (lane IN ('MAIN','ZERO_DTE')),
    underlying TEXT NOT NULL,
    expiration TEXT NOT NULL,
    family TEXT NOT NULL,
    shape TEXT NOT NULL,
    structure_key TEXT NOT NULL,
    lots INTEGER NOT NULL CHECK (lots > 0),
    fill_per_share REAL NOT NULL,
    commission_usd REAL NOT NULL CHECK (commission_usd >= 0),
    max_loss_usd REAL NOT NULL CHECK (max_loss_usd > 0),
    note TEXT,
    record_json TEXT NOT NULL CHECK (json_valid(record_json))
);
CREATE INDEX idx_engine_trades_expiration ON engine_trades (expiration);

CREATE TABLE engine_trade_closes (
    trade_id INTEGER PRIMARY KEY REFERENCES engine_trades(id),
    closed_at TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('MANUAL','EXPIRY')),
    cash_per_share REAL NOT NULL,
    underlying_price REAL,
    commission_usd REAL NOT NULL DEFAULT 0 CHECK (commission_usd >= 0),
    pnl_usd REAL NOT NULL
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
CREATE TRIGGER trg_engine_trades_no_update BEFORE UPDATE ON engine_trades
BEGIN SELECT RAISE(ABORT,'engine trades are immutable'); END;
CREATE TRIGGER trg_engine_trades_no_delete BEFORE DELETE ON engine_trades
BEGIN SELECT RAISE(ABORT,'engine trades are immutable'); END;
CREATE TRIGGER trg_engine_trade_closes_no_update BEFORE UPDATE ON engine_trade_closes
BEGIN SELECT RAISE(ABORT,'engine trade closes are immutable'); END;
CREATE TRIGGER trg_engine_trade_closes_no_delete BEFORE DELETE ON engine_trade_closes
BEGIN SELECT RAISE(ABORT,'engine trade closes are immutable'); END;

INSERT INTO schema_version(version, applied_at)
SELECT 39, strftime('%Y-%m-%dT%H:%M:%SZ','now')
WHERE NOT EXISTS (SELECT 1 FROM schema_version WHERE version=39);
