-- =====================================================================
-- Christiania — migration 005
--
-- Provider evidence hardening
--
-- Preconditions are checked by the Python migration runner.
--
-- Adds:
--   1. Contract multiplier storage on normalized option quotes.
--   2. Separate provider-model observations for IV / Greeks.
--   3. Separate Saxo underlying observations.
--   4. Separate Saxo option observations.
--   5. Saxo resolution-failure observations.
--   6. Observation / ingestion timestamp separation.
--   7. Quote-quality persistence.
-- =====================================================================


PRAGMA foreign_keys = ON;


-- =====================================================================
-- OPTION CONTRACT MULTIPLIER
-- =====================================================================

ALTER TABLE option_quotes
ADD COLUMN shares_per_contract REAL
CHECK (
    shares_per_contract IS NULL
    OR shares_per_contract > 0
);


-- =====================================================================
-- PROVIDER MODEL OBSERVATIONS
-- =====================================================================

CREATE TABLE provider_model_observations (
    id                  INTEGER PRIMARY KEY,

    option_quote_id     INTEGER NOT NULL
                        REFERENCES option_quotes(id),

    provider            TEXT    NOT NULL,

    ingested_at         TEXT    NOT NULL,
    observed_at         TEXT,

    source              TEXT    NOT NULL
                        DEFAULT 'PROVIDER_DERIVED',

    model_name          TEXT,
    provider_request_id TEXT,

    implied_volatility  REAL,
    delta               REAL,
    gamma               REAL,
    theta               REAL,
    vega                REAL,

    CHECK (
        source = 'PROVIDER_DERIVED'
    ),

    CHECK (
        length(trim(provider)) > 0
    ),

    CHECK (
        implied_volatility IS NULL
        OR implied_volatility >= 0
    ),

    CHECK (
        delta IS NULL
        OR delta BETWEEN -1.0 AND 1.0
    ),

    CHECK (
        implied_volatility IS NOT NULL
        OR delta IS NOT NULL
        OR gamma IS NOT NULL
        OR theta IS NOT NULL
        OR vega IS NOT NULL
    )
);


CREATE INDEX idx_provider_model_option_quote
ON provider_model_observations(option_quote_id);


CREATE INDEX idx_provider_model_provider
ON provider_model_observations(provider);


CREATE INDEX idx_provider_model_ingested_at
ON provider_model_observations(ingested_at);


-- =====================================================================
-- SAXO UNDERLYING OBSERVATIONS
-- =====================================================================

CREATE TABLE saxo_underlying_observations (
    id                          INTEGER PRIMARY KEY,

    research_snapshot_id        INTEGER NOT NULL
                                REFERENCES market_snapshots(id),

    underlying                  TEXT    NOT NULL,

    uic                         INTEGER NOT NULL,
    asset_type                  TEXT    NOT NULL,

    ingested_at                 TEXT    NOT NULL,
    observed_at                 TEXT,

    source_snapshot_captured_at TEXT    NOT NULL,

    ingestion_gap_seconds       REAL,

    bid                         REAL,
    ask                         REAL,

    provider_mid                REAL,
    computed_mid                REAL,
    reference_price             REAL,

    bid_size                    REAL,
    ask_size                    REAL,

    delayed_by_minutes          INTEGER,

    market_state                TEXT,

    price_source                TEXT,
    price_source_type           TEXT,

    price_type_bid              TEXT,
    price_type_ask              TEXT,

    quote_quality               TEXT    NOT NULL,

    is_executable               INTEGER NOT NULL,

    CHECK (
        length(trim(underlying)) > 0
    ),

    CHECK (
        length(trim(asset_type)) > 0
    ),

    CHECK (
        bid IS NULL
        OR bid >= 0
    ),

    CHECK (
        ask IS NULL
        OR ask >= 0
    ),

    CHECK (
        provider_mid IS NULL
        OR provider_mid >= 0
    ),

    CHECK (
        computed_mid IS NULL
        OR computed_mid >= 0
    ),

    CHECK (
        reference_price IS NULL
        OR reference_price >= 0
    ),

    CHECK (
        ask IS NULL
        OR bid IS NULL
        OR ask >= bid
    ),

    CHECK (
        bid_size IS NULL
        OR bid_size >= 0
    ),

    CHECK (
        ask_size IS NULL
        OR ask_size >= 0
    ),

    CHECK (
        delayed_by_minutes IS NULL
        OR delayed_by_minutes >= 0
    ),

    CHECK (
        ingestion_gap_seconds IS NULL
        OR ingestion_gap_seconds >= 0
    ),

    CHECK (
        quote_quality IN (
            'EXECUTABLE',
            'DELAYED',
            'INDICATIVE',
            'STALE',
            'UNAVAILABLE'
        )
    ),

    CHECK (
        is_executable IN (0, 1)
    ),

    CHECK (
        (
            quote_quality = 'EXECUTABLE'
            AND is_executable = 1
        )
        OR
        (
            quote_quality <> 'EXECUTABLE'
            AND is_executable = 0
        )
    )
);


CREATE INDEX idx_saxo_underlying_snapshot
ON saxo_underlying_observations(
    research_snapshot_id
);


CREATE INDEX idx_saxo_underlying_symbol
ON saxo_underlying_observations(
    underlying
);


CREATE INDEX idx_saxo_underlying_uic
ON saxo_underlying_observations(
    uic
);


CREATE INDEX idx_saxo_underlying_ingested_at
ON saxo_underlying_observations(
    ingested_at
);


-- =====================================================================
-- SAXO OPTION OBSERVATIONS
-- =====================================================================

CREATE TABLE saxo_option_observations (
    id                          INTEGER PRIMARY KEY,

    option_quote_id             INTEGER NOT NULL
                                REFERENCES option_quotes(id),

    ingested_at                 TEXT    NOT NULL,
    observed_at                 TEXT,

    source_snapshot_captured_at TEXT    NOT NULL,
    source_quote_at             TEXT,

    ingestion_gap_seconds       REAL,

    uic                         INTEGER NOT NULL,
    option_root_id              INTEGER NOT NULL,
    underlying_uic              INTEGER,

    underlying                  TEXT    NOT NULL,

    right                       TEXT    NOT NULL,
    strike                      REAL    NOT NULL,
    expiration                  TEXT    NOT NULL,

    trading_status              TEXT,

    contract_size               REAL,

    bid                         REAL,
    ask                         REAL,

    provider_mid                REAL,
    computed_mid                REAL,

    bid_size                    REAL,
    ask_size                    REAL,

    delayed_by_minutes          INTEGER,

    market_state                TEXT,

    price_source                TEXT,
    price_source_type           TEXT,

    price_type_bid              TEXT,
    price_type_ask              TEXT,

    quote_quality               TEXT    NOT NULL,

    is_executable               INTEGER NOT NULL,

    CHECK (
        right IN ('C', 'P')
    ),

    CHECK (
        strike > 0
    ),

    CHECK (
        contract_size IS NULL
        OR contract_size > 0
    ),

    CHECK (
        bid IS NULL
        OR bid >= 0
    ),

    CHECK (
        ask IS NULL
        OR ask >= 0
    ),

    CHECK (
        provider_mid IS NULL
        OR provider_mid >= 0
    ),

    CHECK (
        computed_mid IS NULL
        OR computed_mid >= 0
    ),

    CHECK (
        ask IS NULL
        OR bid IS NULL
        OR ask >= bid
    ),

    CHECK (
        bid_size IS NULL
        OR bid_size >= 0
    ),

    CHECK (
        ask_size IS NULL
        OR ask_size >= 0
    ),

    CHECK (
        delayed_by_minutes IS NULL
        OR delayed_by_minutes >= 0
    ),

    CHECK (
        ingestion_gap_seconds IS NULL
        OR ingestion_gap_seconds >= 0
    ),

    CHECK (
        quote_quality IN (
            'EXECUTABLE',
            'DELAYED',
            'INDICATIVE',
            'STALE',
            'UNAVAILABLE'
        )
    ),

    CHECK (
        is_executable IN (0, 1)
    ),

    CHECK (
        (
            quote_quality = 'EXECUTABLE'
            AND is_executable = 1
        )
        OR
        (
            quote_quality <> 'EXECUTABLE'
            AND is_executable = 0
        )
    )
);


CREATE INDEX idx_saxo_option_quote
ON saxo_option_observations(
    option_quote_id
);


CREATE INDEX idx_saxo_option_uic
ON saxo_option_observations(
    uic
);


CREATE INDEX idx_saxo_option_underlying
ON saxo_option_observations(
    underlying
);


CREATE INDEX idx_saxo_option_expiration
ON saxo_option_observations(
    expiration
);


CREATE INDEX idx_saxo_option_quality
ON saxo_option_observations(
    quote_quality
);


CREATE INDEX idx_saxo_option_ingested_at
ON saxo_option_observations(
    ingested_at
);


-- =====================================================================
-- SAXO RESOLUTION FAILURES
-- =====================================================================

CREATE TABLE saxo_resolution_failures (
    id                          INTEGER PRIMARY KEY,

    research_snapshot_id        INTEGER NOT NULL
                                REFERENCES market_snapshots(id),

    option_quote_id             INTEGER NOT NULL
                                REFERENCES option_quotes(id),

    attempted_at                TEXT    NOT NULL,

    underlying                  TEXT    NOT NULL,

    provider_contract_id        TEXT,
    option_symbol               TEXT,

    right                       TEXT    NOT NULL,
    strike                      REAL    NOT NULL,
    expiration                  TEXT    NOT NULL,

    shares_per_contract         REAL,

    failure_stage               TEXT    NOT NULL,

    failure_code                TEXT,

    failure_reason              TEXT    NOT NULL,

    CHECK (
        right IN ('C', 'P')
    ),

    CHECK (
        strike > 0
    ),

    CHECK (
        shares_per_contract IS NULL
        OR shares_per_contract > 0
    ),

    CHECK (
        failure_stage IN (
            'ROOT_RESOLUTION',
            'CONTRACT_RESOLUTION',
            'IDENTITY_VALIDATION',
            'QUOTE_FETCH',
            'UNDERLYING_FETCH',
            'AUTHENTICATION',
            'NETWORK',
            'UNKNOWN'
        )
    ),

    CHECK (
        length(trim(failure_reason)) > 0
    )
);


CREATE INDEX idx_saxo_failure_snapshot
ON saxo_resolution_failures(
    research_snapshot_id
);


CREATE INDEX idx_saxo_failure_quote
ON saxo_resolution_failures(
    option_quote_id
);


CREATE INDEX idx_saxo_failure_underlying
ON saxo_resolution_failures(
    underlying
);


CREATE INDEX idx_saxo_failure_stage
ON saxo_resolution_failures(
    failure_stage
);


CREATE INDEX idx_saxo_failure_attempted_at
ON saxo_resolution_failures(
    attempted_at
);


-- =====================================================================
-- INTEGRITY TRIGGERS
-- =====================================================================

CREATE TRIGGER trg_saxo_underlying_snapshot_exists
BEFORE INSERT
ON saxo_underlying_observations
BEGIN
    SELECT CASE
        WHEN NOT EXISTS (
            SELECT 1
            FROM market_snapshots
            WHERE id = NEW.research_snapshot_id
        )
        THEN RAISE(
            ABORT,
            'Saxo underlying observation requires a valid research snapshot.'
        )
    END;
END;


CREATE TRIGGER trg_saxo_option_snapshot_identity
BEFORE INSERT
ON saxo_option_observations
BEGIN
    SELECT CASE
        WHEN NOT EXISTS (
            SELECT 1
            FROM option_quotes AS oq
            JOIN market_snapshots AS ms
              ON ms.id = oq.snapshot_id
            WHERE oq.id = NEW.option_quote_id
              AND ms.captured_at = NEW.source_snapshot_captured_at
        )
        THEN RAISE(
            ABORT,
            'Saxo option observation does not match the source snapshot timestamp.'
        )
    END;
END;


CREATE TRIGGER trg_saxo_failure_same_snapshot
BEFORE INSERT
ON saxo_resolution_failures
BEGIN
    SELECT CASE
        WHEN (
            SELECT snapshot_id
            FROM option_quotes
            WHERE id = NEW.option_quote_id
        ) <> NEW.research_snapshot_id
        THEN RAISE(
            ABORT,
            'Saxo resolution failure must belong to the option quote research snapshot.'
        )
    END;
END;


CREATE TRIGGER trg_saxo_option_contract_identity
BEFORE INSERT
ON saxo_option_observations
BEGIN
    SELECT CASE
        WHEN NOT EXISTS (
            SELECT 1
            FROM option_quotes AS oq
            WHERE oq.id = NEW.option_quote_id
              AND oq.right = NEW.right
              AND abs(oq.strike - NEW.strike) <= 0.000001
              AND substr(oq.expiration, 1, 10)
                  = substr(NEW.expiration, 1, 10)
        )
        THEN RAISE(
            ABORT,
            'Saxo observation contract identity does not match the source option quote.'
        )
    END;
END;


-- =====================================================================
-- IMMUTABILITY
-- =====================================================================

CREATE TRIGGER trg_provider_model_no_update
BEFORE UPDATE
ON provider_model_observations
BEGIN
    SELECT RAISE(
        ABORT,
        'Provider model observations are immutable evidence.'
    );
END;


CREATE TRIGGER trg_provider_model_no_delete
BEFORE DELETE
ON provider_model_observations
BEGIN
    SELECT RAISE(
        ABORT,
        'Provider model observations cannot be deleted.'
    );
END;


CREATE TRIGGER trg_saxo_underlying_no_update
BEFORE UPDATE
ON saxo_underlying_observations
BEGIN
    SELECT RAISE(
        ABORT,
        'Saxo underlying observations are immutable evidence.'
    );
END;


CREATE TRIGGER trg_saxo_underlying_no_delete
BEFORE DELETE
ON saxo_underlying_observations
BEGIN
    SELECT RAISE(
        ABORT,
        'Saxo underlying observations cannot be deleted.'
    );
END;


CREATE TRIGGER trg_saxo_option_no_update
BEFORE UPDATE
ON saxo_option_observations
BEGIN
    SELECT RAISE(
        ABORT,
        'Saxo option observations are immutable evidence.'
    );
END;


CREATE TRIGGER trg_saxo_option_no_delete
BEFORE DELETE
ON saxo_option_observations
BEGIN
    SELECT RAISE(
        ABORT,
        'Saxo option observations cannot be deleted.'
    );
END;


CREATE TRIGGER trg_saxo_failure_no_update
BEFORE UPDATE
ON saxo_resolution_failures
BEGIN
    SELECT RAISE(
        ABORT,
        'Saxo resolution failures are immutable evidence.'
    );
END;


CREATE TRIGGER trg_saxo_failure_no_delete
BEFORE DELETE
ON saxo_resolution_failures
BEGIN
    SELECT RAISE(
        ABORT,
        'Saxo resolution failures cannot be deleted.'
    );
END;


-- =====================================================================
-- RESEARCH QUALITY VIEW
-- =====================================================================

CREATE VIEW v_saxo_option_evidence AS
SELECT
    so.id AS saxo_observation_id,

    oq.id AS option_quote_id,
    oq.snapshot_id,

    ms.captured_at AS massive_snapshot_captured_at,
    ms.underlying AS massive_underlying,

    oq.provider_contract_id,
    oq.option_symbol,

    oq.right,
    oq.strike,
    oq.expiration,
    oq.shares_per_contract AS massive_multiplier,

    so.uic AS saxo_uic,
    so.option_root_id AS saxo_option_root_id,
    so.underlying_uic AS saxo_underlying_uic,

    so.contract_size AS saxo_multiplier,

    so.ingested_at AS saxo_ingested_at,
    so.observed_at AS saxo_observed_at,

    so.ingestion_gap_seconds,

    so.bid AS saxo_bid,
    so.ask AS saxo_ask,
    so.provider_mid AS saxo_provider_mid,
    so.computed_mid AS saxo_computed_mid,

    so.bid_size AS saxo_bid_size,
    so.ask_size AS saxo_ask_size,

    so.delayed_by_minutes,
    so.market_state,

    so.price_source,
    so.price_source_type,

    so.price_type_bid,
    so.price_type_ask,

    so.quote_quality,
    so.is_executable

FROM saxo_option_observations AS so

JOIN option_quotes AS oq
  ON oq.id = so.option_quote_id

JOIN market_snapshots AS ms
  ON ms.id = oq.snapshot_id;


-- =====================================================================
-- VERSION
-- =====================================================================

INSERT INTO schema_version (
    version,
    applied_at
)
VALUES (
    5,
    strftime(
        '%Y-%m-%dT%H:%M:%SZ',
        'now'
    )
);