-- =====================================================================
-- Christiania — native schema v6
--
-- Generated from the verified live v6 database schema.
--
-- Design rules:
--   1. Original prediction evidence is immutable.
--   2. Entry market evidence is immutable.
--   3. Paper/live provenance is immutable.
--   4. Annotations are append-only.
--   5. Rejected decisions are recorded.
--   6. Bad records are preserved by voiding rather than deleting.
--   7. Research observations and provider evidence are immutable.
--   8. Research runs preserve failures and normalization drops.
--   9. Pre-resolution selections are frozen before Saxo resolution.
--  10. Cohort metadata records preregistration and code identity.
--
-- Conventions:
--   * Timestamps: ISO-8601 UTC strings.
--   * Prices/Greeks/IV: REAL.
--   * Cash/fees/max loss: INTEGER minor currency units.
--   * Probabilities: REAL in [0,1].
-- =====================================================================

PRAGMA foreign_keys = ON;


-- =====================================================================
-- TABLES
-- =====================================================================

-- annotations
CREATE TABLE annotations (
    id          INTEGER PRIMARY KEY,
    trade_id    INTEGER NOT NULL REFERENCES trades(id) ON DELETE CASCADE,
    created_at  TEXT    NOT NULL,
    body        TEXT    NOT NULL,
    CHECK (length(trim(body)) > 0)
);

-- candidate_controls
CREATE TABLE candidate_controls (
    id                INTEGER PRIMARY KEY,

    candidate_id      INTEGER NOT NULL
                      REFERENCES candidates(id),

    control_quote_id  INTEGER NOT NULL
                      REFERENCES option_quotes(id),

    matching_version  TEXT NOT NULL,

    match_rank        INTEGER NOT NULL,

    match_distance    REAL,

    created_at        TEXT NOT NULL,

    UNIQUE (
        candidate_id,
        control_quote_id
    ),

    CHECK (
        match_rank > 0
    ),

    CHECK (
        match_distance IS NULL
        OR match_distance >= 0
    )
);

-- candidate_legs
CREATE TABLE candidate_legs (
    id               INTEGER PRIMARY KEY,

    candidate_id     INTEGER NOT NULL
                     REFERENCES candidates(id),

    leg_no           INTEGER NOT NULL,

    option_quote_id  INTEGER NOT NULL
                     REFERENCES option_quotes(id),

    direction        TEXT NOT NULL,

    contracts        INTEGER NOT NULL
                     DEFAULT 1,

    UNIQUE (
        candidate_id,
        leg_no
    ),

    CHECK (
        direction IN ('BUY', 'SELL')
    ),

    CHECK (
        contracts > 0
    )
);

-- candidates
CREATE TABLE candidates (
    id                          INTEGER PRIMARY KEY,

    created_at                  TEXT NOT NULL,

    snapshot_id                 INTEGER NOT NULL
                                REFERENCES market_snapshots(id),

    underlying                  TEXT NOT NULL,

    candidate_source            TEXT NOT NULL,

    candidate_class             TEXT NOT NULL,

    scanner_version             TEXT NOT NULL,
    rule_set_version            TEXT NOT NULL,
    rule_id                     TEXT NOT NULL,
    outcome_definition_version  TEXT NOT NULL,

    rationale                   TEXT NOT NULL,

    model_probability_profit    REAL,
    model_expected_value_minor  INTEGER,
    model_max_loss_minor        INTEGER,
    model_confidence            REAL,

    status                      TEXT NOT NULL
                                DEFAULT 'TRACKING', preregistration_hash TEXT, code_git_sha TEXT,

    CHECK (
        candidate_source IN (
            'MANUAL_RESEARCH',
            'CHRISTIANIA_SCANNER'
        )
    ),

    CHECK (
        candidate_class IN (
            'CORE',
            'ASYMMETRIC',
            'RESEARCH_ONLY'
        )
    ),

    CHECK (
        status IN (
            'TRACKING',
            'WATCH',
            'PAPER',
            'LIVE',
            'REJECTED',
            'RESOLVED'
        )
    ),

    CHECK (
        model_probability_profit IS NULL
        OR model_probability_profit BETWEEN 0.0 AND 1.0
    ),

    CHECK (
        model_max_loss_minor IS NULL
        OR model_max_loss_minor >= 0
    ),

    CHECK (
        model_confidence IS NULL
        OR model_confidence BETWEEN 0.0 AND 1.0
    ),

    CHECK (
        length(trim(rationale)) > 0
    )
);

-- market_snapshots
CREATE TABLE market_snapshots (
    id                    INTEGER PRIMARY KEY,

    captured_at           TEXT NOT NULL,
    underlying            TEXT NOT NULL,
    provider              TEXT NOT NULL,
    provider_snapshot_id  TEXT,

    underlying_price      REAL,
    underlying_source     TEXT NOT NULL,
    underlying_at         TEXT,

    fx_to_eur             REAL,
    fx_source             TEXT NOT NULL,
    fx_at                 TEXT,

    notes                 TEXT, research_run_id INTEGER
REFERENCES research_runs(id), us_session_date TEXT, us_session_state TEXT
CHECK (
    us_session_state IS NULL
    OR us_session_state IN (
        'PRE_OPEN',
        'INTRADAY',
        'POST_CLOSE',
        'NON_TRADING_DAY'
    )
),

    CHECK (
        underlying_source IN (
            'MANUAL',
            'FETCHED',
            'DERIVED',
            'UNKNOWN'
        )
    ),

    CHECK (
        fx_source IN (
            'MANUAL',
            'FETCHED',
            'DERIVED',
            'UNKNOWN'
        )
    ),

    CHECK (
        underlying_price IS NULL
        OR underlying_price >= 0
    ),

    CHECK (
        fx_to_eur IS NULL
        OR fx_to_eur > 0
    ),

    CHECK (
        (
            underlying_price IS NULL
            AND underlying_source = 'UNKNOWN'
        )
        OR
        (
            underlying_price IS NOT NULL
            AND underlying_source <> 'UNKNOWN'
        )
    ),

    CHECK (
        (
            fx_to_eur IS NULL
            AND fx_source = 'UNKNOWN'
        )
        OR
        (
            fx_to_eur IS NOT NULL
            AND fx_source <> 'UNKNOWN'
        )
    )
);

-- normalization_drops
CREATE TABLE normalization_drops (
    id                      INTEGER PRIMARY KEY,

    run_id                  INTEGER NOT NULL
                            REFERENCES research_runs(id),

    snapshot_id             INTEGER
                            REFERENCES market_snapshots(id),

    provider                TEXT    NOT NULL,
    underlying              TEXT    NOT NULL,

    provider_contract_id    TEXT,
    option_symbol           TEXT,

    raw_contract_type       TEXT,
    raw_strike              TEXT,
    raw_expiration          TEXT,

    reason_code             TEXT    NOT NULL,
    reason_detail           TEXT,

    dropped_at              TEXT    NOT NULL,

    raw_payload_json        TEXT,

    CHECK (
        reason_code IN (
            'UNSUPPORTED_CONTRACT_TYPE',
            'MISSING_STRIKE',
            'MISSING_EXPIRATION',
            'INVALID_STRIKE',
            'INVALID_EXPIRATION',
            'MISSING_CONTRACT_IDENTIFIER',
            'OTHER_NORMALIZATION_FAILURE'
        )
    ),

    CHECK (
        length(trim(provider)) > 0
    ),

    CHECK (
        length(trim(underlying)) > 0
    )
);

-- option_quotes
CREATE TABLE option_quotes (
    id                    INTEGER PRIMARY KEY,

    snapshot_id           INTEGER NOT NULL
                          REFERENCES market_snapshots(id),

    provider_contract_id  TEXT,
    option_symbol         TEXT,

    right                 TEXT NOT NULL,
    strike                REAL NOT NULL,
    expiration            TEXT NOT NULL,

    quote_at              TEXT,

    bid                   REAL,
    bid_source            TEXT NOT NULL,
    bid_at                TEXT,

    ask                   REAL,
    ask_source            TEXT NOT NULL,
    ask_at                TEXT,

    last                  REAL,
    last_source           TEXT NOT NULL,
    last_at               TEXT,

    implied_volatility    REAL,
    iv_source             TEXT NOT NULL,
    iv_at                 TEXT,

    delta                 REAL,
    delta_source          TEXT NOT NULL,
    delta_at              TEXT,

    gamma                 REAL,
    gamma_source          TEXT NOT NULL,
    gamma_at              TEXT,

    theta                 REAL,
    theta_source          TEXT NOT NULL,
    theta_at              TEXT,

    vega                  REAL,
    vega_source           TEXT NOT NULL,
    vega_at               TEXT,

    volume                INTEGER,
    volume_source         TEXT NOT NULL,
    volume_at             TEXT,

    open_interest         INTEGER,
    open_interest_source  TEXT NOT NULL,
    open_interest_at      TEXT, shares_per_contract REAL
CHECK (
    shares_per_contract IS NULL
    OR shares_per_contract > 0
), open_interest_as_of_date TEXT, volume_trading_date TEXT,

    CHECK (
        right IN ('C', 'P')
    ),

    CHECK (
        strike > 0
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
        last IS NULL
        OR last >= 0
    ),

    CHECK (
        ask IS NULL
        OR bid IS NULL
        OR ask >= bid
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
        volume IS NULL
        OR volume >= 0
    ),

    CHECK (
        open_interest IS NULL
        OR open_interest >= 0
    ),

    CHECK (
        bid_source IN (
            'MANUAL',
            'FETCHED',
            'DERIVED',
            'UNKNOWN'
        )
    ),

    CHECK (
        ask_source IN (
            'MANUAL',
            'FETCHED',
            'DERIVED',
            'UNKNOWN'
        )
    ),

    CHECK (
        last_source IN (
            'MANUAL',
            'FETCHED',
            'DERIVED',
            'UNKNOWN'
        )
    ),

    CHECK (
        iv_source IN (
            'MANUAL',
            'FETCHED',
            'DERIVED',
            'UNKNOWN'
        )
    ),

    CHECK (
        delta_source IN (
            'MANUAL',
            'FETCHED',
            'DERIVED',
            'UNKNOWN'
        )
    ),

    CHECK (
        gamma_source IN (
            'MANUAL',
            'FETCHED',
            'DERIVED',
            'UNKNOWN'
        )
    ),

    CHECK (
        theta_source IN (
            'MANUAL',
            'FETCHED',
            'DERIVED',
            'UNKNOWN'
        )
    ),

    CHECK (
        vega_source IN (
            'MANUAL',
            'FETCHED',
            'DERIVED',
            'UNKNOWN'
        )
    ),

    CHECK (
        volume_source IN (
            'MANUAL',
            'FETCHED',
            'DERIVED',
            'UNKNOWN'
        )
    ),

    CHECK (
        open_interest_source IN (
            'MANUAL',
            'FETCHED',
            'DERIVED',
            'UNKNOWN'
        )
    ),

    CHECK (
        (bid IS NULL AND bid_source = 'UNKNOWN')
        OR
        (bid IS NOT NULL AND bid_source <> 'UNKNOWN')
    ),

    CHECK (
        (ask IS NULL AND ask_source = 'UNKNOWN')
        OR
        (ask IS NOT NULL AND ask_source <> 'UNKNOWN')
    ),

    CHECK (
        (last IS NULL AND last_source = 'UNKNOWN')
        OR
        (last IS NOT NULL AND last_source <> 'UNKNOWN')
    ),

    CHECK (
        (
            implied_volatility IS NULL
            AND iv_source = 'UNKNOWN'
        )
        OR
        (
            implied_volatility IS NOT NULL
            AND iv_source <> 'UNKNOWN'
        )
    ),

    CHECK (
        (delta IS NULL AND delta_source = 'UNKNOWN')
        OR
        (delta IS NOT NULL AND delta_source <> 'UNKNOWN')
    ),

    CHECK (
        (gamma IS NULL AND gamma_source = 'UNKNOWN')
        OR
        (gamma IS NOT NULL AND gamma_source <> 'UNKNOWN')
    ),

    CHECK (
        (theta IS NULL AND theta_source = 'UNKNOWN')
        OR
        (theta IS NOT NULL AND theta_source <> 'UNKNOWN')
    ),

    CHECK (
        (vega IS NULL AND vega_source = 'UNKNOWN')
        OR
        (vega IS NOT NULL AND vega_source <> 'UNKNOWN')
    ),

    CHECK (
        (volume IS NULL AND volume_source = 'UNKNOWN')
        OR
        (volume IS NOT NULL AND volume_source <> 'UNKNOWN')
    ),

    CHECK (
        (
            open_interest IS NULL
            AND open_interest_source = 'UNKNOWN'
        )
        OR
        (
            open_interest IS NOT NULL
            AND open_interest_source <> 'UNKNOWN'
        )
    )
);

-- provider_model_observations
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
    vega                REAL, model_underlying_price REAL
CHECK (
    model_underlying_price IS NULL
    OR model_underlying_price >= 0
), model_rate REAL, model_dividend_yield REAL, model_input_notes TEXT,

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

-- research_provider_attempts
CREATE TABLE research_provider_attempts (
    id              INTEGER PRIMARY KEY,

    run_id          INTEGER NOT NULL
                    REFERENCES research_runs(id),

    provider        TEXT    NOT NULL,
    operation       TEXT    NOT NULL,
    underlying      TEXT,

    attempted_at    TEXT    NOT NULL,
    completed_at    TEXT,

    succeeded       INTEGER NOT NULL,

    retry_count     INTEGER NOT NULL DEFAULT 0,

    request_id      TEXT,

    failure_code    TEXT,
    failure_reason  TEXT,

    CHECK (
        length(trim(provider)) > 0
    ),

    CHECK (
        length(trim(operation)) > 0
    ),

    CHECK (
        succeeded IN (0,1)
    ),

    CHECK (
        retry_count >= 0
    ),

    CHECK (
        (
            succeeded = 0
            AND failure_reason IS NOT NULL
            AND length(trim(failure_reason)) > 0
        )
        OR
        (
            succeeded = 1
            AND failure_reason IS NULL
        )
    )
);

-- research_run_underlyings
CREATE TABLE research_run_underlyings (
    id              INTEGER PRIMARY KEY,

    run_id          INTEGER NOT NULL
                    REFERENCES research_runs(id),

    underlying      TEXT    NOT NULL,
    attempted_at    TEXT    NOT NULL,
    completed_at    TEXT,

    status          TEXT    NOT NULL,

    retry_count     INTEGER NOT NULL DEFAULT 0,

    failure_code    TEXT,
    failure_reason  TEXT,

    UNIQUE (
        run_id,
        underlying
    ),

    CHECK (
        length(trim(underlying)) > 0
    ),

    CHECK (
        status IN (
            'ATTEMPTED',
            'SUCCESS',
            'FAILED'
        )
    ),

    CHECK (
        retry_count >= 0
    ),

    CHECK (
        (
            status = 'FAILED'
            AND failure_reason IS NOT NULL
            AND length(trim(failure_reason)) > 0
        )
        OR
        (
            status <> 'FAILED'
            AND failure_reason IS NULL
        )
    )
);

-- research_runs
CREATE TABLE research_runs (
    id                          INTEGER PRIMARY KEY,

    cohort_id                   TEXT    NOT NULL,
    preregistration_hash        TEXT    NOT NULL,
    code_git_sha                TEXT    NOT NULL,

    started_at                  TEXT    NOT NULL,
    ended_at                    TEXT,

    us_session_date             TEXT    NOT NULL,
    us_session_state            TEXT    NOT NULL,

    status                      TEXT    NOT NULL
                                DEFAULT 'STARTED',

    attempted_underlyings       INTEGER NOT NULL DEFAULT 0,
    succeeded_underlyings       INTEGER NOT NULL DEFAULT 0,
    failed_underlyings          INTEGER NOT NULL DEFAULT 0,

    provider_requests_attempted INTEGER NOT NULL DEFAULT 0,
    provider_requests_succeeded INTEGER NOT NULL DEFAULT 0,
    provider_requests_failed    INTEGER NOT NULL DEFAULT 0,

    massive_raw_contracts       INTEGER,
    massive_normalized_contracts INTEGER,
    normalization_drop_count    INTEGER,

    selected_strata_count       INTEGER,
    empty_strata_count          INTEGER,
    selected_contract_count     INTEGER,

    saxo_resolution_success_count INTEGER,
    saxo_resolution_failure_count INTEGER,

    underlying_observation_status TEXT,

    notes                       TEXT,

    CHECK (
        length(trim(cohort_id)) > 0
    ),

    CHECK (
        length(trim(preregistration_hash)) > 0
    ),

    CHECK (
        length(trim(code_git_sha)) > 0
    ),

    CHECK (
        us_session_state IN (
            'PRE_OPEN',
            'INTRADAY',
            'POST_CLOSE',
            'NON_TRADING_DAY'
        )
    ),

    CHECK (
        status IN (
            'STARTED',
            'COLLECTING',
            'COMPLETED',
            'FAILED',
            'INVALID'
        )
    ),

    CHECK (
        underlying_observation_status IS NULL
        OR underlying_observation_status IN (
            'SUCCESS',
            'FAILED',
            'NOT_ATTEMPTED'
        )
    ),

    CHECK (attempted_underlyings >= 0),
    CHECK (succeeded_underlyings >= 0),
    CHECK (failed_underlyings >= 0),

    CHECK (provider_requests_attempted >= 0),
    CHECK (provider_requests_succeeded >= 0),
    CHECK (provider_requests_failed >= 0),

    CHECK (
        massive_raw_contracts IS NULL
        OR massive_raw_contracts >= 0
    ),

    CHECK (
        massive_normalized_contracts IS NULL
        OR massive_normalized_contracts >= 0
    ),

    CHECK (
        normalization_drop_count IS NULL
        OR normalization_drop_count >= 0
    ),

    CHECK (
        selected_strata_count IS NULL
        OR selected_strata_count >= 0
    ),

    CHECK (
        empty_strata_count IS NULL
        OR empty_strata_count >= 0
    ),

    CHECK (
        selected_contract_count IS NULL
        OR selected_contract_count >= 0
    ),

    CHECK (
        saxo_resolution_success_count IS NULL
        OR saxo_resolution_success_count >= 0
    ),

    CHECK (
        saxo_resolution_failure_count IS NULL
        OR saxo_resolution_failure_count >= 0
    ),

    CHECK (
        ended_at IS NULL
        OR status IN (
            'COMPLETED',
            'FAILED',
            'INVALID'
        )
    ),

    CHECK (
        status NOT IN (
            'COMPLETED',
            'FAILED',
            'INVALID'
        )
        OR ended_at IS NOT NULL
    )
);

-- research_selections
CREATE TABLE research_selections (
    id                      INTEGER PRIMARY KEY,

    run_id                  INTEGER NOT NULL
                            REFERENCES research_runs(id),

    option_quote_id         INTEGER NOT NULL
                            REFERENCES option_quotes(id),

    selected_at             TEXT    NOT NULL,

    selection_rule          TEXT    NOT NULL,

    dte_stratum             TEXT    NOT NULL,
    delta_stratum           TEXT    NOT NULL,
    option_right            TEXT    NOT NULL,

    resolution_sequence     INTEGER NOT NULL,

    preregistration_hash    TEXT    NOT NULL,
    code_git_sha            TEXT    NOT NULL,

    UNIQUE (
        run_id,
        option_quote_id
    ),

    UNIQUE (
        run_id,
        resolution_sequence
    ),

    CHECK (
        option_right IN (
            'C',
            'P'
        )
    ),

    CHECK (
        resolution_sequence > 0
    ),

    CHECK (
        length(trim(selection_rule)) > 0
    ),

    CHECK (
        length(trim(preregistration_hash)) > 0
    ),

    CHECK (
        length(trim(code_git_sha)) > 0
    )
);

-- saxo_option_observations
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

    is_executable               INTEGER NOT NULL, quote_quality_version TEXT NOT NULL
DEFAULT 'SAXO_QUOTE_CLASSIFIER_V1', is_stale INTEGER NOT NULL DEFAULT 0
CHECK (is_stale IN (0,1)), is_indicative INTEGER NOT NULL DEFAULT 0
CHECK (is_indicative IN (0,1)), is_delayed INTEGER NOT NULL DEFAULT 0
CHECK (is_delayed IN (0,1)), is_locked INTEGER NOT NULL DEFAULT 0
CHECK (is_locked IN (0,1)), is_crossed INTEGER NOT NULL DEFAULT 0
CHECK (is_crossed IN (0,1)), observation_gap_seconds REAL
CHECK (
    observation_gap_seconds IS NULL
    OR observation_gap_seconds >= 0
), retry_count INTEGER NOT NULL DEFAULT 0
CHECK (retry_count >= 0), resolution_sequence INTEGER
CHECK (
    resolution_sequence IS NULL
    OR resolution_sequence > 0
),

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

-- saxo_resolution_failures
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

    failure_reason              TEXT    NOT NULL, retry_count INTEGER NOT NULL DEFAULT 0
CHECK (retry_count >= 0), resolution_sequence INTEGER
CHECK (
    resolution_sequence IS NULL
    OR resolution_sequence > 0
),

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

-- saxo_underlying_observations
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

    is_executable               INTEGER NOT NULL, quote_quality_version TEXT NOT NULL
DEFAULT 'SAXO_QUOTE_CLASSIFIER_V1', is_stale INTEGER NOT NULL DEFAULT 0
CHECK (is_stale IN (0,1)), is_indicative INTEGER NOT NULL DEFAULT 0
CHECK (is_indicative IN (0,1)), is_delayed INTEGER NOT NULL DEFAULT 0
CHECK (is_delayed IN (0,1)), is_locked INTEGER NOT NULL DEFAULT 0
CHECK (is_locked IN (0,1)), is_crossed INTEGER NOT NULL DEFAULT 0
CHECK (is_crossed IN (0,1)), observation_gap_seconds REAL
CHECK (
    observation_gap_seconds IS NULL
    OR observation_gap_seconds >= 0
), retry_count INTEGER NOT NULL DEFAULT 0
CHECK (retry_count >= 0),

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

-- schema_version
CREATE TABLE schema_version (
    version     INTEGER NOT NULL,
    applied_at  TEXT    NOT NULL
);

-- trade_legs
CREATE TABLE trade_legs (
    id              INTEGER PRIMARY KEY,
    trade_id        INTEGER NOT NULL REFERENCES trades(id) ON DELETE CASCADE,
    leg_no          INTEGER NOT NULL,

    right           TEXT    NOT NULL,     -- 'C' or 'P'
    direction       TEXT    NOT NULL,     -- 'BUY' or 'SELL'
    strike          REAL    NOT NULL,
    expiration      TEXT    NOT NULL,     -- 'YYYY-MM-DD'
    contracts       INTEGER NOT NULL,
    multiplier      INTEGER NOT NULL DEFAULT 100,

    entry_bid       REAL    NOT NULL,
    entry_ask       REAL    NOT NULL,
    entry_fill      REAL    NOT NULL,     -- what you actually got

    exit_bid        REAL,
    exit_ask        REAL,
    exit_fill       REAL, entry_quote_at TEXT, entry_iv REAL, entry_delta REAL,

    UNIQUE (trade_id, leg_no),
    CHECK (right     IN ('C','P')),
    CHECK (direction IN ('BUY','SELL')),
    CHECK (contracts > 0),
    CHECK (strike    > 0),
    CHECK (entry_ask >= entry_bid),
    CHECK (exit_ask  IS NULL OR exit_bid IS NULL OR exit_ask >= exit_bid)
);

-- trades
CREATE TABLE trades (
    id                    INTEGER PRIMARY KEY,

    -- Provenance -----------------------------------------------------
    created_at            TEXT    NOT NULL,   -- when the row was written
    underlying            TEXT    NOT NULL,   -- ticker, e.g. 'META'
    currency              TEXT    NOT NULL DEFAULT 'USD',

    status                TEXT    NOT NULL DEFAULT 'OPEN',
    parent_trade_id       INTEGER REFERENCES trades(id),  -- set on a roll
    strategy              TEXT,               -- 'LONG_CALL', 'DEBIT_SPREAD', ...

    -- Entry: market state at the moment of fill ----------------------
    -- NULL for REJECTED rows. Immutable once written.
    entry_at              TEXT,               -- fill time, not record time
    entry_underlying      REAL,
    entry_fx_rate         REAL,               -- currency -> EUR at fill
    entry_fees            INTEGER,            -- minor units, >= 0
    entry_cash            INTEGER,            -- net cash flow, minor units
                                              -- negative = debit paid

    -- Prediction: written once, never revised ------------------------
    thesis                TEXT    NOT NULL,   -- why this trade
    prediction            TEXT    NOT NULL,   -- what specifically happens
    horizon_date          TEXT    NOT NULL,   -- by when
    p_thesis              REAL    NOT NULL,   -- P(prediction comes true)
    p_profit              REAL    NOT NULL,   -- P(trade closes profitable)
    invalidation          TEXT    NOT NULL,   -- what proves me wrong

    -- Risk plan: written once ----------------------------------------
    max_loss              INTEGER NOT NULL,   -- minor units, >= 0
    profit_target         TEXT    NOT NULL,
    stop_condition        TEXT    NOT NULL,

    -- Rejection / voiding --------------------------------------------
    rejection_reason      TEXT,               -- required iff REJECTED
    voided_at             TEXT,               -- set when preserving a bad row
    void_reason           TEXT,               -- required iff VOIDED

    -- Exit: mutable, written at close --------------------------------
    exit_at               TEXT,
    exit_underlying       REAL,
    exit_fx_rate          REAL,
    exit_fees             INTEGER,
    exit_cash             INTEGER,            -- positive = proceeds
    exit_reason           TEXT,               -- 'TARGET','STOP','INVALIDATED',
                                              -- 'EXPIRY','ROLL','DISCRETIONARY'

    -- Resolution: the two questions, scored separately ---------------
    thesis_correct        INTEGER,            -- 0/1, set at resolution
    was_profitable        INTEGER,            -- 0/1, NULL for REJECTED
    resolved_at           TEXT, is_paper INTEGER NOT NULL DEFAULT 1
CHECK (is_paper IN (0, 1)), p_thesis_initial REAL, entry_iv_rank REAL, next_earnings_date TEXT,

    CHECK (status IN ('OPEN','CLOSED','EXPIRED','ASSIGNED','ROLLED','REJECTED','VOIDED')),
    CHECK (p_thesis >= 0.0 AND p_thesis <= 1.0),
    CHECK (p_profit >= 0.0 AND p_profit <= 1.0),
    CHECK (max_loss >= 0),
    CHECK (entry_fees IS NULL OR entry_fees >= 0),
    CHECK (exit_fees  IS NULL OR exit_fees  >= 0),
    CHECK (thesis_correct IS NULL OR thesis_correct IN (0,1)),
    CHECK (was_profitable IS NULL OR was_profitable IN (0,1)),
    CHECK (length(trim(thesis))       > 0),
    CHECK (length(trim(prediction))   > 0),
    CHECK (length(trim(invalidation)) > 0),
    -- Decision-state integrity.
    CHECK (
        (status = 'REJECTED'
             AND entry_at IS NULL
             AND rejection_reason IS NOT NULL
             AND length(trim(rejection_reason)) > 0
             AND voided_at IS NULL
             AND void_reason IS NULL)
        OR
        (status = 'VOIDED'
             AND voided_at IS NOT NULL
             AND void_reason IS NOT NULL
             AND length(trim(void_reason)) > 0)
        OR
        (status NOT IN ('REJECTED','VOIDED')
             AND entry_at IS NOT NULL
             AND entry_underlying IS NOT NULL
             AND entry_fx_rate IS NOT NULL
             AND entry_fx_rate > 0
             AND entry_fees IS NOT NULL
             AND entry_cash IS NOT NULL
             AND rejection_reason IS NULL
             AND voided_at IS NULL
             AND void_reason IS NULL)
    ),

    -- Exit-state integrity. Closed outcomes must have complete trade-level
    -- exit evidence; OPEN/REJECTED rows must have none. VOIDED rows preserve
    -- whatever evidence existed before they were voided.
    CHECK (
        (status = 'OPEN'
             AND exit_at IS NULL
             AND exit_underlying IS NULL
             AND exit_fx_rate IS NULL
             AND exit_fees IS NULL
             AND exit_cash IS NULL
             AND exit_reason IS NULL)
        OR
        (status IN ('CLOSED','EXPIRED','ASSIGNED','ROLLED')
             AND exit_at IS NOT NULL
             AND exit_underlying IS NOT NULL
             AND exit_fx_rate IS NOT NULL
             AND exit_fx_rate > 0
             AND exit_fees IS NOT NULL
             AND exit_cash IS NOT NULL
             AND exit_reason IS NOT NULL
             AND length(trim(exit_reason)) > 0)
        OR
        (status = 'REJECTED'
             AND exit_at IS NULL
             AND exit_underlying IS NULL
             AND exit_fx_rate IS NULL
             AND exit_fees IS NULL
             AND exit_cash IS NULL
             AND exit_reason IS NULL)
        OR
        (status = 'VOIDED')
    ),

    -- Resolution-state integrity. Resolution is all-or-nothing. Rejected
    -- decisions resolve the thesis only; traded decisions resolve both.
    CHECK (
        (resolved_at IS NULL
             AND thesis_correct IS NULL
             AND was_profitable IS NULL)
        OR
        (resolved_at IS NOT NULL
             AND thesis_correct IS NOT NULL
             AND (
                 (status = 'REJECTED' AND was_profitable IS NULL)
                 OR
                 (status IN ('CLOSED','EXPIRED','ASSIGNED','ROLLED')
                      AND was_profitable IS NOT NULL)
             ))
    )
);


-- =====================================================================
-- INDEXES
-- =====================================================================

-- idx_annotations_trade
CREATE INDEX idx_annotations_trade ON annotations(trade_id);

-- idx_candidate_controls_candidate
CREATE INDEX idx_candidate_controls_candidate
ON candidate_controls(candidate_id);

-- idx_candidate_controls_quote
CREATE INDEX idx_candidate_controls_quote
ON candidate_controls(control_quote_id);

-- idx_candidate_legs_candidate
CREATE INDEX idx_candidate_legs_candidate
ON candidate_legs(candidate_id);

-- idx_candidate_legs_quote
CREATE INDEX idx_candidate_legs_quote
ON candidate_legs(option_quote_id);

-- idx_candidates_rule
CREATE INDEX idx_candidates_rule
ON candidates(rule_id);

-- idx_candidates_snapshot
CREATE INDEX idx_candidates_snapshot
ON candidates(snapshot_id);

-- idx_candidates_status
CREATE INDEX idx_candidates_status
ON candidates(status);

-- idx_legs_trade
CREATE INDEX idx_legs_trade ON trade_legs(trade_id);

-- idx_market_snapshots_captured_at
CREATE INDEX idx_market_snapshots_captured_at
ON market_snapshots(captured_at);

-- idx_market_snapshots_provider
CREATE INDEX idx_market_snapshots_provider
ON market_snapshots(provider);

-- idx_market_snapshots_underlying
CREATE INDEX idx_market_snapshots_underlying
ON market_snapshots(underlying);

-- idx_normalization_drops_reason
CREATE INDEX idx_normalization_drops_reason
ON normalization_drops(reason_code);

-- idx_normalization_drops_run
CREATE INDEX idx_normalization_drops_run
ON normalization_drops(run_id);

-- idx_option_quotes_delta
CREATE INDEX idx_option_quotes_delta
ON option_quotes(delta);

-- idx_option_quotes_expiration
CREATE INDEX idx_option_quotes_expiration
ON option_quotes(expiration);

-- idx_option_quotes_snapshot
CREATE INDEX idx_option_quotes_snapshot
ON option_quotes(snapshot_id);

-- idx_option_quotes_symbol
CREATE INDEX idx_option_quotes_symbol
ON option_quotes(option_symbol);

-- idx_provider_attempts_provider
CREATE INDEX idx_provider_attempts_provider
ON research_provider_attempts(provider);

-- idx_provider_attempts_run
CREATE INDEX idx_provider_attempts_run
ON research_provider_attempts(run_id);

-- idx_provider_model_ingested_at
CREATE INDEX idx_provider_model_ingested_at
ON provider_model_observations(ingested_at);

-- idx_provider_model_option_quote
CREATE INDEX idx_provider_model_option_quote
ON provider_model_observations(option_quote_id);

-- idx_provider_model_provider
CREATE INDEX idx_provider_model_provider
ON provider_model_observations(provider);

-- idx_research_runs_cohort
CREATE INDEX idx_research_runs_cohort
ON research_runs(cohort_id);

-- idx_research_runs_started_at
CREATE INDEX idx_research_runs_started_at
ON research_runs(started_at);

-- idx_research_runs_status
CREATE INDEX idx_research_runs_status
ON research_runs(status);

-- idx_research_selections_quote
CREATE INDEX idx_research_selections_quote
ON research_selections(option_quote_id);

-- idx_research_selections_run
CREATE INDEX idx_research_selections_run
ON research_selections(run_id);

-- idx_run_underlyings_run
CREATE INDEX idx_run_underlyings_run
ON research_run_underlyings(run_id);

-- idx_saxo_failure_attempted_at
CREATE INDEX idx_saxo_failure_attempted_at
ON saxo_resolution_failures(
    attempted_at
);

-- idx_saxo_failure_quote
CREATE INDEX idx_saxo_failure_quote
ON saxo_resolution_failures(
    option_quote_id
);

-- idx_saxo_failure_snapshot
CREATE INDEX idx_saxo_failure_snapshot
ON saxo_resolution_failures(
    research_snapshot_id
);

-- idx_saxo_failure_stage
CREATE INDEX idx_saxo_failure_stage
ON saxo_resolution_failures(
    failure_stage
);

-- idx_saxo_failure_underlying
CREATE INDEX idx_saxo_failure_underlying
ON saxo_resolution_failures(
    underlying
);

-- idx_saxo_option_expiration
CREATE INDEX idx_saxo_option_expiration
ON saxo_option_observations(
    expiration
);

-- idx_saxo_option_ingested_at
CREATE INDEX idx_saxo_option_ingested_at
ON saxo_option_observations(
    ingested_at
);

-- idx_saxo_option_quality
CREATE INDEX idx_saxo_option_quality
ON saxo_option_observations(
    quote_quality
);

-- idx_saxo_option_quote
CREATE INDEX idx_saxo_option_quote
ON saxo_option_observations(
    option_quote_id
);

-- idx_saxo_option_uic
CREATE INDEX idx_saxo_option_uic
ON saxo_option_observations(
    uic
);

-- idx_saxo_option_underlying
CREATE INDEX idx_saxo_option_underlying
ON saxo_option_observations(
    underlying
);

-- idx_saxo_underlying_ingested_at
CREATE INDEX idx_saxo_underlying_ingested_at
ON saxo_underlying_observations(
    ingested_at
);

-- idx_saxo_underlying_snapshot
CREATE INDEX idx_saxo_underlying_snapshot
ON saxo_underlying_observations(
    research_snapshot_id
);

-- idx_saxo_underlying_symbol
CREATE INDEX idx_saxo_underlying_symbol
ON saxo_underlying_observations(
    underlying
);

-- idx_saxo_underlying_uic
CREATE INDEX idx_saxo_underlying_uic
ON saxo_underlying_observations(
    uic
);

-- idx_trades_entry_at
CREATE INDEX idx_trades_entry_at   ON trades(entry_at);

-- idx_trades_parent
CREATE INDEX idx_trades_parent     ON trades(parent_trade_id);

-- idx_trades_status
CREATE INDEX idx_trades_status     ON trades(status);

-- idx_trades_underlying
CREATE INDEX idx_trades_underlying ON trades(underlying);


-- =====================================================================
-- TRIGGERS
-- =====================================================================

-- trg_annotations_no_delete
CREATE TRIGGER trg_annotations_no_delete
BEFORE DELETE ON annotations
BEGIN
    SELECT RAISE(ABORT, 'Annotations are append-only.');
END;

-- trg_annotations_no_update
CREATE TRIGGER trg_annotations_no_update
BEFORE UPDATE ON annotations
BEGIN
    SELECT RAISE(ABORT, 'Annotations are append-only.');
END;

-- trg_candidate_control_not_candidate_leg
CREATE TRIGGER trg_candidate_control_not_candidate_leg
BEFORE INSERT
ON candidate_controls
BEGIN
    SELECT CASE
        WHEN EXISTS (
            SELECT 1
            FROM candidate_legs
            WHERE candidate_id = NEW.candidate_id
              AND option_quote_id = NEW.control_quote_id
        )
        THEN RAISE(
            ABORT,
            'Candidate leg cannot also be its own matched control.'
        )
    END;
END;

-- trg_candidate_control_same_snapshot
CREATE TRIGGER trg_candidate_control_same_snapshot
BEFORE INSERT
ON candidate_controls
BEGIN
    SELECT CASE
        WHEN (
            SELECT snapshot_id
            FROM candidates
            WHERE id = NEW.candidate_id
        ) <> (
            SELECT snapshot_id
            FROM option_quotes
            WHERE id = NEW.control_quote_id
        )
        THEN RAISE(
            ABORT,
            'Matched control must come from the candidate snapshot.'
        )
    END;
END;

-- trg_candidate_controls_no_delete
CREATE TRIGGER trg_candidate_controls_no_delete
BEFORE DELETE
ON candidate_controls
BEGIN
    SELECT RAISE(
        ABORT,
        'Matched controls cannot be deleted.'
    );
END;

-- trg_candidate_controls_no_update
CREATE TRIGGER trg_candidate_controls_no_update
BEFORE UPDATE
ON candidate_controls
BEGIN
    SELECT RAISE(
        ABORT,
        'Matched controls are immutable.'
    );
END;

-- trg_candidate_definition_immutable
CREATE TRIGGER trg_candidate_definition_immutable
BEFORE UPDATE OF
    created_at,
    snapshot_id,
    underlying,
    candidate_source,
    candidate_class,
    scanner_version,
    rule_set_version,
    rule_id,
    outcome_definition_version,
    rationale,
    model_probability_profit,
    model_expected_value_minor,
    model_max_loss_minor,
    model_confidence
ON candidates
BEGIN
    SELECT RAISE(
        ABORT,
        'Candidate definition is immutable.'
    );
END;

-- trg_candidate_leg_same_snapshot
CREATE TRIGGER trg_candidate_leg_same_snapshot
BEFORE INSERT
ON candidate_legs
BEGIN
    SELECT CASE
        WHEN (
            SELECT snapshot_id
            FROM candidates
            WHERE id = NEW.candidate_id
        ) <> (
            SELECT snapshot_id
            FROM option_quotes
            WHERE id = NEW.option_quote_id
        )
        THEN RAISE(
            ABORT,
            'Candidate leg must come from the candidate snapshot.'
        )
    END;
END;

-- trg_candidate_legs_no_delete
CREATE TRIGGER trg_candidate_legs_no_delete
BEFORE DELETE
ON candidate_legs
BEGIN
    SELECT RAISE(
        ABORT,
        'Candidate legs cannot be deleted.'
    );
END;

-- trg_candidate_legs_no_update
CREATE TRIGGER trg_candidate_legs_no_update
BEFORE UPDATE
ON candidate_legs
BEGIN
    SELECT RAISE(
        ABORT,
        'Candidate legs are immutable.'
    );
END;

-- trg_legs_entry_immutable
CREATE TRIGGER trg_legs_entry_immutable
BEFORE UPDATE OF
    trade_id,
    leg_no,
    right,
    direction,
    strike,
    expiration,
    contracts,
    multiplier,
    entry_quote_at,
    entry_iv,
    entry_delta,
    entry_bid,
    entry_ask,
    entry_fill
ON trade_legs
BEGIN
    SELECT RAISE(
        ABORT,
        'Leg entry data is immutable.'
    );
END;

-- trg_legs_no_delete
CREATE TRIGGER trg_legs_no_delete
BEFORE DELETE ON trade_legs
BEGIN
    SELECT RAISE(ABORT, 'Trade legs cannot be deleted.');
END;

-- trg_market_snapshots_no_delete
CREATE TRIGGER trg_market_snapshots_no_delete
BEFORE DELETE
ON market_snapshots
BEGIN
    SELECT RAISE(
        ABORT,
        'Market snapshots cannot be deleted.'
    );
END;

-- trg_market_snapshots_no_update
CREATE TRIGGER trg_market_snapshots_no_update
BEFORE UPDATE
ON market_snapshots
BEGIN
    SELECT RAISE(
        ABORT,
        'Market snapshots are immutable evidence.'
    );
END;

-- trg_no_legs_on_rejected
CREATE TRIGGER trg_no_legs_on_rejected
BEFORE INSERT ON trade_legs
WHEN (SELECT status FROM trades WHERE id = NEW.trade_id) IN ('REJECTED','VOIDED')
BEGIN
    SELECT RAISE(ABORT, 'A rejected or voided decision cannot acquire new legs.');
END;

-- trg_normalization_drops_no_delete
CREATE TRIGGER trg_normalization_drops_no_delete
BEFORE DELETE
ON normalization_drops
BEGIN
    SELECT RAISE(
        ABORT,
        'Normalization drops cannot be deleted.'
    );
END;

-- trg_normalization_drops_no_update
CREATE TRIGGER trg_normalization_drops_no_update
BEFORE UPDATE
ON normalization_drops
BEGIN
    SELECT RAISE(
        ABORT,
        'Normalization drops are immutable evidence.'
    );
END;

-- trg_option_quotes_no_delete
CREATE TRIGGER trg_option_quotes_no_delete
BEFORE DELETE
ON option_quotes
BEGIN
    SELECT RAISE(
        ABORT,
        'Option quotes cannot be deleted.'
    );
END;

-- trg_option_quotes_no_update
CREATE TRIGGER trg_option_quotes_no_update
BEFORE UPDATE
ON option_quotes
BEGIN
    SELECT RAISE(
        ABORT,
        'Option quotes are immutable evidence.'
    );
END;

-- trg_provider_attempts_no_delete
CREATE TRIGGER trg_provider_attempts_no_delete
BEFORE DELETE
ON research_provider_attempts
BEGIN
    SELECT RAISE(
        ABORT,
        'Provider attempts cannot be deleted.'
    );
END;

-- trg_provider_attempts_no_update
CREATE TRIGGER trg_provider_attempts_no_update
BEFORE UPDATE
ON research_provider_attempts
BEGIN
    SELECT RAISE(
        ABORT,
        'Provider attempts are immutable evidence.'
    );
END;

-- trg_provider_model_no_delete
CREATE TRIGGER trg_provider_model_no_delete
BEFORE DELETE
ON provider_model_observations
BEGIN
    SELECT RAISE(
        ABORT,
        'Provider model observations cannot be deleted.'
    );
END;

-- trg_provider_model_no_update
CREATE TRIGGER trg_provider_model_no_update
BEFORE UPDATE
ON provider_model_observations
BEGIN
    SELECT RAISE(
        ABORT,
        'Provider model observations are immutable evidence.'
    );
END;

-- trg_research_run_terminal_immutable
CREATE TRIGGER trg_research_run_terminal_immutable
BEFORE UPDATE
ON research_runs
WHEN OLD.status IN (
    'COMPLETED',
    'FAILED',
    'INVALID'
)
BEGIN
    SELECT RAISE(
        ABORT,
        'Terminal research runs are immutable.'
    );
END;

-- trg_research_runs_no_delete
CREATE TRIGGER trg_research_runs_no_delete
BEFORE DELETE
ON research_runs
BEGIN
    SELECT RAISE(
        ABORT,
        'Research runs cannot be deleted.'
    );
END;

-- trg_research_selections_no_delete
CREATE TRIGGER trg_research_selections_no_delete
BEFORE DELETE
ON research_selections
BEGIN
    SELECT RAISE(
        ABORT,
        'Research selections cannot be deleted.'
    );
END;

-- trg_research_selections_no_update
CREATE TRIGGER trg_research_selections_no_update
BEFORE UPDATE
ON research_selections
BEGIN
    SELECT RAISE(
        ABORT,
        'Research selections are immutable after selection.'
    );
END;

-- trg_saxo_failure_no_delete
CREATE TRIGGER trg_saxo_failure_no_delete
BEFORE DELETE
ON saxo_resolution_failures
BEGIN
    SELECT RAISE(
        ABORT,
        'Saxo resolution failures cannot be deleted.'
    );
END;

-- trg_saxo_failure_no_update
CREATE TRIGGER trg_saxo_failure_no_update
BEFORE UPDATE
ON saxo_resolution_failures
BEGIN
    SELECT RAISE(
        ABORT,
        'Saxo resolution failures are immutable evidence.'
    );
END;

-- trg_saxo_failure_same_snapshot
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

-- trg_saxo_option_contract_identity
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

-- trg_saxo_option_no_delete
CREATE TRIGGER trg_saxo_option_no_delete
BEFORE DELETE
ON saxo_option_observations
BEGIN
    SELECT RAISE(
        ABORT,
        'Saxo option observations cannot be deleted.'
    );
END;

-- trg_saxo_option_no_update
CREATE TRIGGER trg_saxo_option_no_update
BEFORE UPDATE
ON saxo_option_observations
BEGIN
    SELECT RAISE(
        ABORT,
        'Saxo option observations are immutable evidence.'
    );
END;

-- trg_saxo_option_snapshot_identity
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

-- trg_saxo_underlying_no_delete
CREATE TRIGGER trg_saxo_underlying_no_delete
BEFORE DELETE
ON saxo_underlying_observations
BEGIN
    SELECT RAISE(
        ABORT,
        'Saxo underlying observations cannot be deleted.'
    );
END;

-- trg_saxo_underlying_no_update
CREATE TRIGGER trg_saxo_underlying_no_update
BEFORE UPDATE
ON saxo_underlying_observations
BEGIN
    SELECT RAISE(
        ABORT,
        'Saxo underlying observations are immutable evidence.'
    );
END;

-- trg_saxo_underlying_snapshot_exists
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

-- trg_selection_quote_belongs_to_run
CREATE TRIGGER trg_selection_quote_belongs_to_run
BEFORE INSERT
ON research_selections
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
            'Selected contract must belong to the research run snapshot.'
        )
    END;
END;

-- trg_status_terminal
CREATE TRIGGER trg_status_terminal
BEFORE UPDATE OF status ON trades
WHEN OLD.status <> NEW.status AND OLD.status <> 'OPEN'
BEGIN
    SELECT RAISE(ABORT, 'Only OPEN trades may transition to another status.');
END;

-- trg_trades_entry_immutable
CREATE TRIGGER trg_trades_entry_immutable
BEFORE UPDATE OF
    created_at,
    entry_at,
    entry_underlying,
    entry_fx_rate,
    entry_fees,
    entry_cash,
    underlying,
    currency,
    is_paper
ON trades
BEGIN
    SELECT RAISE(
        ABORT,
        'Entry data and provenance are immutable. Correct the record by voiding it, not editing it.'
    );
END;

-- trg_trades_no_delete
CREATE TRIGGER trg_trades_no_delete
BEFORE DELETE ON trades
BEGIN
    SELECT RAISE(ABORT, 'Trades cannot be deleted. Mark an invalid record VOIDED.');
END;

-- trg_trades_prediction_immutable
CREATE TRIGGER trg_trades_prediction_immutable
BEFORE UPDATE OF
    thesis,
    prediction,
    horizon_date,
    p_thesis_initial,
    p_thesis,
    p_profit,
    invalidation,
    max_loss,
    profit_target,
    stop_condition
ON trades
BEGIN
    SELECT RAISE(
        ABORT,
        'Prediction and risk fields are immutable. Add an annotation instead.'
    );
END;

-- trg_trades_resolution_write_once
CREATE TRIGGER trg_trades_resolution_write_once
BEFORE UPDATE OF thesis_correct, was_profitable, resolved_at ON trades
WHEN OLD.resolved_at IS NOT NULL
BEGIN
    SELECT RAISE(ABORT,
        'This trade is already resolved. Add an annotation instead.');
END;

-- trg_void_write_once
CREATE TRIGGER trg_void_write_once
BEFORE UPDATE OF voided_at, void_reason ON trades
WHEN OLD.voided_at IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'A voided trade is already locked.');
END;


-- =====================================================================
-- VIEWS
-- =====================================================================

-- v_calibration
CREATE VIEW v_calibration AS
SELECT id, resolved_at, status, 'THESIS' AS question,
       p_thesis AS p, thesis_correct AS outcome,
       (p_thesis - thesis_correct) * (p_thesis - thesis_correct) AS brier
FROM trades
WHERE thesis_correct IS NOT NULL
UNION ALL
SELECT id, resolved_at, status, 'PROFIT' AS question,
       p_profit AS p, was_profitable AS outcome,
       (p_profit - was_profitable) * (p_profit - was_profitable) AS brier
FROM trades
WHERE was_profitable IS NOT NULL;

-- v_calibration_buckets
CREATE VIEW v_calibration_buckets AS
SELECT
    question,
    MIN(CAST(p * 10 AS INTEGER), 9) AS bucket, -- 0 = 0-10%, 9 = 90-100%
    COUNT(*)                     AS n,
    ROUND(AVG(p), 3)             AS mean_p,
    ROUND(AVG(outcome), 3)       AS hit_rate,
    ROUND(AVG(brier), 4)         AS mean_brier
FROM v_calibration
GROUP BY question, bucket;

-- v_open_positions
CREATE VIEW v_open_positions AS
SELECT
    t.id,
    t.underlying,
    t.strategy,
    t.entry_at,
    t.horizon_date,
    t.p_thesis,
    t.p_profit,
    t.max_loss,
    COUNT(l.id)                            AS legs,
    MIN(l.expiration)                      AS nearest_expiry,
    CAST(julianday(MIN(l.expiration)) - julianday('now') AS INTEGER) AS dte
FROM trades t
LEFT JOIN trade_legs l ON l.trade_id = t.id
WHERE t.status = 'OPEN'
GROUP BY t.id;

-- v_realized_pnl
CREATE VIEW v_realized_pnl AS
SELECT
    t.id,
    t.underlying,
    t.currency,
    t.entry_at,
    t.exit_at,
    t.exit_reason,
    (COALESCE(t.entry_cash, 0) + COALESCE(t.exit_cash, 0)
       - COALESCE(t.entry_fees, 0) - COALESCE(t.exit_fees, 0)) AS pnl_minor,
    t.thesis_correct,
    t.was_profitable
FROM trades t
WHERE t.status IN ('CLOSED','EXPIRED','ASSIGNED','ROLLED');

-- v_research_run_reconciliation
CREATE VIEW v_research_run_reconciliation AS
SELECT
    rr.id AS run_id,
    rr.cohort_id,
    rr.status,

    rr.massive_raw_contracts,
    rr.massive_normalized_contracts,
    rr.normalization_drop_count,

    CASE
        WHEN
            rr.massive_raw_contracts IS NULL
            OR rr.massive_normalized_contracts IS NULL
            OR rr.normalization_drop_count IS NULL
        THEN NULL

        WHEN
            rr.massive_raw_contracts
            =
            rr.massive_normalized_contracts
            + rr.normalization_drop_count
        THEN 1

        ELSE 0
    END AS normalization_reconciles,

    rr.selected_contract_count,
    rr.saxo_resolution_success_count,
    rr.saxo_resolution_failure_count,

    CASE
        WHEN
            rr.selected_contract_count IS NULL
            OR rr.saxo_resolution_success_count IS NULL
            OR rr.saxo_resolution_failure_count IS NULL
        THEN NULL

        WHEN
            rr.selected_contract_count
            =
            rr.saxo_resolution_success_count
            + rr.saxo_resolution_failure_count
        THEN 1

        ELSE 0
    END AS resolution_reconciles

FROM research_runs AS rr;

-- v_saxo_option_evidence
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

-- v_slippage
CREATE VIEW v_slippage AS
SELECT
    l.trade_id,
    l.leg_no,
    l.direction,
    (l.entry_bid + l.entry_ask) / 2.0                          AS entry_mid,
    CASE WHEN l.direction = 'BUY'
         THEN l.entry_fill - (l.entry_bid + l.entry_ask) / 2.0
         ELSE (l.entry_bid + l.entry_ask) / 2.0 - l.entry_fill
    END                                                        AS entry_slip,
    CASE WHEN l.exit_fill IS NULL THEN NULL
         WHEN l.direction = 'BUY'
         THEN (l.exit_bid + l.exit_ask) / 2.0 - l.exit_fill
         ELSE l.exit_fill - (l.exit_bid + l.exit_ask) / 2.0
    END                                                        AS exit_slip,
    (l.entry_ask - l.entry_bid)
        / NULLIF((l.entry_bid + l.entry_ask) / 2.0, 0)         AS entry_spread_pct
FROM trade_legs l;


-- =====================================================================
-- SCHEMA VERSION
-- =====================================================================

DELETE FROM schema_version;

INSERT INTO schema_version (
    version,
    applied_at
)
VALUES (
    6,
    strftime(
        '%Y-%m-%dT%H:%M:%SZ',
        'now'
    )
);
