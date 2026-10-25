-- Christiania schema v38: one canonical, append-only prospective decision book.
-- Strictly freezes candidate-generation inputs and skipped/approved verdicts
-- before any measured outcome. Actual outcomes remain a separate evidence tier.

PRAGMA foreign_keys = ON;

CREATE TABLE unified_candidate_decisions_v1 (
    id INTEGER PRIMARY KEY,
    research_run_id INTEGER NOT NULL REFERENCES research_runs(id),
    snapshot_id INTEGER NOT NULL REFERENCES market_snapshots(id),
    underlying TEXT NOT NULL,
    expiration TEXT NOT NULL,
    lane TEXT NOT NULL CHECK (lane IN ('MAIN','CASINO')),
    strategy_id TEXT NOT NULL,
    asof_at TEXT NOT NULL,
    frozen_at TEXT NOT NULL,
    source_reference TEXT NOT NULL,
    input_sha256 TEXT NOT NULL UNIQUE
      CHECK (length(input_sha256)=64),
    input_json TEXT NOT NULL CHECK(json_valid(input_json)),
    model_version TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN
      ('NO_TRADE','CANDIDATE_FOR_MANUAL_REQUOTE_NOT_EXECUTABLE')),
    rank INTEGER,
    conservative_net_ev_usd TEXT,
    modeled_all_in_risk_usd TEXT,
    risk_adjusted_score TEXT,
    confirming_model_groups INTEGER NOT NULL DEFAULT 0
      CHECK (confirming_model_groups>=0),
    opposing_model_groups INTEGER NOT NULL DEFAULT 0
      CHECK (opposing_model_groups>=0),
    blockers_json TEXT NOT NULL CHECK(json_valid(blockers_json)),
    forecast_lineage_json TEXT NOT NULL CHECK(json_valid(forecast_lineage_json)),
    exit_rule TEXT NOT NULL,
    provenance_tier TEXT NOT NULL CHECK(provenance_tier IN
      ('UNPROVEN_MODEL','PROSPECTIVE_CONTROLLED_MODEL')),
    CHECK (rank IS NULL OR rank>=1),
    CHECK (json_type(input_json)='object'),
    CHECK (json_type(blockers_json)='array'),
    CHECK (json_type(forecast_lineage_json)='array'),
    UNIQUE (research_run_id,snapshot_id,lane,strategy_id,source_reference)
);

CREATE INDEX idx_unified_decisions_recent
    ON unified_candidate_decisions_v1
    (research_run_id, snapshot_id, lane, state);

CREATE INDEX idx_unified_decisions_followup
    ON unified_candidate_decisions_v1
    (underlying, expiration, state);

CREATE TRIGGER trg_unified_decisions_no_update
BEFORE UPDATE ON unified_candidate_decisions_v1
BEGIN SELECT RAISE(ABORT, 'unified decisions are immutable'); END;

CREATE TRIGGER trg_unified_decisions_no_delete
BEFORE DELETE ON unified_candidate_decisions_v1
BEGIN SELECT RAISE(ABORT, 'unified decisions are immutable'); END;

-- Every snapshot gets one immutable attempt disposition, including when
-- missing data prevents any strategy geometry from being emitted.
CREATE TABLE unified_capture_dispositions_v1 (
    id INTEGER PRIMARY KEY,
    research_run_id INTEGER NOT NULL REFERENCES research_runs(id),
    snapshot_id INTEGER NOT NULL UNIQUE REFERENCES market_snapshots(id),
    captured_at TEXT NOT NULL,
    evaluated_at TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN
      ('FROZEN_NO_TRADE','NO_SOURCE','NO_GEOMETRY',
       'OUTSIDE_PROSPECTIVE_WINDOW','EVIDENCE_REJECTED',
       'CAPTURE_FAILURE')),
    reason_code TEXT NOT NULL,
    structures_compared INTEGER NOT NULL DEFAULT 0
       CHECK (structures_compared>=0),
    decisions_frozen INTEGER NOT NULL DEFAULT 0
       CHECK (decisions_frozen>=0),
    CHECK(decisions_frozen<=structures_compared)
);
CREATE INDEX idx_unified_capture_run
    ON unified_capture_dispositions_v1
    (research_run_id,snapshot_id,state);
CREATE TRIGGER trg_unified_capture_no_update
BEFORE UPDATE ON unified_capture_dispositions_v1
BEGIN SELECT RAISE(ABORT,'unified capture dispositions are immutable'); END;
CREATE TRIGGER trg_unified_capture_no_delete
BEFORE DELETE ON unified_capture_dispositions_v1
BEGIN SELECT RAISE(ABORT,'unified capture dispositions are immutable'); END;

INSERT INTO schema_version(version, applied_at)
SELECT 38, strftime('%Y-%m-%dT%H:%M:%SZ','now')
WHERE NOT EXISTS (SELECT 1 FROM schema_version WHERE version=38);
