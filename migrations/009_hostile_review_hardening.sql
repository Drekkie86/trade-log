PRAGMA foreign_keys = ON;

DROP TRIGGER IF EXISTS trg_shadow_state_transition_guard;

CREATE TRIGGER trg_shadow_state_transition_guard
BEFORE INSERT ON shadow_state_events
BEGIN
    SELECT CASE
        WHEN NOT EXISTS (
            SELECT 1 FROM shadow_state_events
            WHERE candidate_id = NEW.candidate_id
        )
        AND (
            NEW.from_state IS NOT NULL
            OR NEW.to_state IS NOT 'SURFACED'
        )
        THEN RAISE(
            ABORT,
            'First shadow state event must be SURFACED.'
        )
    END;

    SELECT CASE
        WHEN EXISTS (
            SELECT 1 FROM shadow_state_events
            WHERE candidate_id = NEW.candidate_id
        )
        AND NEW.from_state IS NOT (
            SELECT to_state
            FROM shadow_state_events
            WHERE candidate_id = NEW.candidate_id
            ORDER BY id DESC
            LIMIT 1
        )
        THEN RAISE(
            ABORT,
            'Shadow state from_state does not match current state.'
        )
    END;

    SELECT CASE
        WHEN EXISTS (
            SELECT 1 FROM shadow_state_events
            WHERE candidate_id = NEW.candidate_id
        )
        AND NOT (
            (NEW.from_state IS 'SURFACED' AND NEW.to_state IS 'INVESTIGATED')
            OR (NEW.from_state IS 'INVESTIGATED' AND NEW.to_state IS 'DECIDED')
            OR (NEW.from_state IS 'DECIDED' AND NEW.to_state IS 'SHADOW_TRACKED')
            OR (NEW.from_state IS 'DECIDED' AND NEW.to_state IS 'REJECTED')
            OR (NEW.from_state IS 'SHADOW_TRACKED' AND NEW.to_state IS 'CLOSED_OR_EXPIRED')
            OR (NEW.from_state IS 'CLOSED_OR_EXPIRED' AND NEW.to_state IS 'SCORED')
        )
        THEN RAISE(
            ABORT,
            'Invalid shadow lifecycle transition.'
        )
    END;
END;

CREATE TRIGGER trg_underlying_pin_first_event
BEFORE INSERT ON underlying_pin_events
WHEN NOT EXISTS (
    SELECT 1 FROM underlying_pin_events
    WHERE candidate_id = NEW.candidate_id
)
AND NEW.action IS NOT 'PIN'
BEGIN
    SELECT RAISE(
        ABORT,
        'First underlying pin event must be PIN.'
    );
END;

CREATE TABLE unmatched_provider_contract_observations (
    id                    INTEGER PRIMARY KEY,
    research_run_id       INTEGER NOT NULL
                          REFERENCES research_runs(id),
    provider              TEXT    NOT NULL,
    evidence_family       TEXT    NOT NULL,
    anomaly_type          TEXT    NOT NULL,
    underlying            TEXT    NOT NULL,
    provider_contract_id  TEXT,
    expiration            TEXT,
    strike                REAL,
    right                 TEXT,
    reason_code           TEXT,
    observed_at           TEXT    NOT NULL,
    raw_timestamp         TEXT,
    raw_payload_json      TEXT,
    ingested_at           TEXT    NOT NULL,

    CHECK (length(trim(provider)) > 0),
    CHECK (length(trim(evidence_family)) > 0),
    CHECK (length(trim(underlying)) > 0),
    CHECK (
        anomaly_type IN (
            'SNAPSHOT_ONLY',
            'THETA_QUOTE_ONLY',
            'THETA_GREEK_ONLY',
            'SAXO_REFERENCE_ONLY',
            'PROVIDER_ONLY'
        )
    ),
    CHECK (
        right IS NULL OR right IN ('C', 'P')
    ),
    CHECK (
        provider_contract_id IS NOT NULL
        OR (
            expiration IS NOT NULL
            AND strike IS NOT NULL
            AND right IS NOT NULL
        )
    )
);

CREATE INDEX idx_unmatched_provider_run
ON unmatched_provider_contract_observations(research_run_id);

CREATE INDEX idx_unmatched_provider_identity
ON unmatched_provider_contract_observations(
    provider,
    underlying,
    expiration,
    strike,
    right
);

CREATE TRIGGER trg_unmatched_provider_no_update
BEFORE UPDATE ON unmatched_provider_contract_observations
BEGIN
    SELECT RAISE(
        ABORT,
        'Unmatched provider contract observations are immutable evidence.'
    );
END;

CREATE TRIGGER trg_unmatched_provider_no_delete
BEFORE DELETE ON unmatched_provider_contract_observations
BEGIN
    SELECT RAISE(
        ABORT,
        'Unmatched provider contract observations cannot be deleted.'
    );
END;

CREATE VIEW v_active_underlying_pins AS
SELECT DISTINCT
    sc.underlying
FROM shadow_candidates AS sc
WHERE EXISTS (
    SELECT 1
    FROM underlying_pin_events AS upe
    WHERE upe.candidate_id = sc.id
      AND upe.id = (
          SELECT MAX(upe2.id)
          FROM underlying_pin_events AS upe2
          WHERE upe2.candidate_id = sc.id
      )
      AND upe.action = 'PIN'
);

INSERT INTO schema_version (
    version,
    applied_at
)
SELECT
    9,
    strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
WHERE NOT EXISTS (
    SELECT 1 FROM schema_version WHERE version = 9
);
