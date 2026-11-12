-- Christiania prospective evidence journal V1: REFERENCE SCHEMA ONLY.
-- NOT in migrations/. Never auto-applied to a production v34 database.
-- Append-only, source-hash-linked observations. Not independent authentication.
PRAGMA foreign_keys = ON;

CREATE TABLE prospective_evidence_events_v1 (
    id                       INTEGER PRIMARY KEY,
    event_key                TEXT NOT NULL UNIQUE,
    opportunity_key          TEXT NOT NULL,
    candidate_id             INTEGER,
    research_run_id          INTEGER,
    strategy_id              TEXT NOT NULL,
    phase                    TEXT NOT NULL,
    event_type               TEXT NOT NULL,
    event_state              TEXT NOT NULL,
    event_at                 TEXT NOT NULL,
    recorded_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    source_family            TEXT NOT NULL,
    source_evidence_sha256   TEXT,
    reason_codes_json        TEXT NOT NULL,
    previous_hash_sha256     TEXT NOT NULL,
    event_hash_sha256        TEXT NOT NULL UNIQUE,

    CHECK(length(trim(event_key)) > 0 AND length(event_key) <= 128),
    CHECK(length(trim(opportunity_key)) > 0 AND length(opportunity_key) <= 128),
    CHECK(length(trim(strategy_id)) > 0 AND length(strategy_id) <= 128),
    CHECK(candidate_id IS NULL OR candidate_id > 0),
    CHECK(research_run_id IS NULL OR research_run_id > 0),
    CHECK(phase IN ('NONE','ENTRY','EXIT')),
    CHECK(event_type IN (
        'OPPORTUNITY', 'PRICE_REQUEST', 'MARKET_REFERENCE', 'NO_TRADE',
        'SOURCE_FAILURE', 'REJECTION'
    )),
    CHECK(event_state IN (
        'RECORDED','UNAVAILABLE','REJECTED','OBSERVED_ONLY','NO_TRADE'
    )),
    CHECK(event_type != 'MARKET_REFERENCE' OR event_state = 'OBSERVED_ONLY'),
    CHECK(event_type != 'NO_TRADE' OR event_state = 'NO_TRADE'),
    CHECK(event_type != 'SOURCE_FAILURE' OR event_state = 'UNAVAILABLE'),
    CHECK(event_type != 'REJECTION' OR event_state = 'REJECTED'),
    CHECK(source_family IN ('NONE','SAXO_LEG','SAXO_MULTILEG','THETADATA','BROKER_PAPER_RECEIPT_REFERENCE')),
    CHECK(
        source_evidence_sha256 IS NULL OR
        (length(source_evidence_sha256)=64 AND source_evidence_sha256 NOT GLOB '*[^0-9a-f]*')
    ),
    CHECK(length(previous_hash_sha256)=64 AND previous_hash_sha256 NOT GLOB '*[^0-9a-f]*'),
    CHECK(length(event_hash_sha256)=64 AND event_hash_sha256 NOT GLOB '*[^0-9a-f]*'),
    CHECK(json_valid(reason_codes_json)),
    CHECK(
        event_type != 'MARKET_REFERENCE' OR
        source_evidence_sha256 IS NOT NULL
    )
);
CREATE INDEX idx_prospective_evidence_opportunity
ON prospective_evidence_events_v1(opportunity_key,id);

-- Exactly one denominator-opening observation for an opportunity.
CREATE UNIQUE INDEX idx_prospective_evidence_one_opener
ON prospective_evidence_events_v1(opportunity_key)
WHERE event_type='OPPORTUNITY';

-- Reject cherry-picked reference events lacking a prior recorded opportunity,
-- and prevent source/exit events being dated earlier than the opportunity.
CREATE TRIGGER trg_prospective_evidence_requires_opportunity
BEFORE INSERT ON prospective_evidence_events_v1
WHEN NEW.event_type != 'OPPORTUNITY'
BEGIN
  SELECT CASE WHEN NOT EXISTS (
    SELECT 1 FROM prospective_evidence_events_v1
    WHERE opportunity_key=NEW.opportunity_key AND event_type='OPPORTUNITY'
      AND event_at <= NEW.event_at
  ) THEN RAISE(ABORT,'Prospective evidence must follow a recorded opportunity')
  END;
END;

CREATE TRIGGER trg_prospective_evidence_immutable_update
BEFORE UPDATE ON prospective_evidence_events_v1
BEGIN
  SELECT RAISE(ABORT,'Prospective evidence cannot be updated');
END;

CREATE TRIGGER trg_prospective_evidence_immutable_delete
BEFORE DELETE ON prospective_evidence_events_v1
BEGIN
  SELECT RAISE(ABORT,'Prospective evidence cannot be deleted');
END;

CREATE TRIGGER trg_prospective_evidence_chain_insert
BEFORE INSERT ON prospective_evidence_events_v1
BEGIN
  SELECT CASE WHEN NEW.previous_hash_sha256 != COALESCE(
      (SELECT event_hash_sha256 FROM prospective_evidence_events_v1
       ORDER BY id DESC LIMIT 1),
      '0000000000000000000000000000000000000000000000000000000000000000'
  )
  THEN RAISE(ABORT,'Prospective evidence chain predecessor mismatch')
  END;
END;
