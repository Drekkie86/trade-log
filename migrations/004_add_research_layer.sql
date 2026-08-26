PRAGMA foreign_keys = ON;

BEGIN TRANSACTION;

-- =====================================================================
-- Christiania — schema v4
--
-- Research layer:
--   market_snapshots
--   option_quotes
--   candidates
--   candidate_legs
--   candidate_controls
--
-- Core principles:
--   * Market evidence is immutable.
--   * Missing objective values are NULL + UNKNOWN.
--   * Numeric zero is never used to represent missing data.
--   * Candidate definitions freeze the rule/model versions that created them.
--   * Candidate legs and matched controls must come from the same snapshot.
-- =====================================================================


-- =====================================================================
-- MARKET SNAPSHOTS
-- =====================================================================

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

    notes                 TEXT,

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


-- =====================================================================
-- OPTION QUOTES
--
-- provider is inherited from market_snapshots.
-- Each field independently records whether it was fetched, derived,
-- manually supplied, or unknown.
-- =====================================================================

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
    open_interest_at      TEXT,

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


-- =====================================================================
-- CANDIDATES
-- =====================================================================

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
                                DEFAULT 'TRACKING',

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


-- =====================================================================
-- CANDIDATE LEGS
--
-- Candidates can eventually represent multi-leg structures.
-- Every leg points to the exact quote Christiania observed.
-- =====================================================================

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


-- =====================================================================
-- MATCHED CONTROLS
--
-- Controls point into the same normalized quote population.
-- They are not a second copy of market data.
-- =====================================================================

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


-- =====================================================================
-- INDEXES
-- =====================================================================

CREATE INDEX idx_market_snapshots_underlying
ON market_snapshots(underlying);

CREATE INDEX idx_market_snapshots_captured_at
ON market_snapshots(captured_at);

CREATE INDEX idx_market_snapshots_provider
ON market_snapshots(provider);

CREATE INDEX idx_option_quotes_snapshot
ON option_quotes(snapshot_id);

CREATE INDEX idx_option_quotes_expiration
ON option_quotes(expiration);

CREATE INDEX idx_option_quotes_symbol
ON option_quotes(option_symbol);

CREATE INDEX idx_option_quotes_delta
ON option_quotes(delta);

CREATE INDEX idx_candidates_snapshot
ON candidates(snapshot_id);

CREATE INDEX idx_candidates_status
ON candidates(status);

CREATE INDEX idx_candidates_rule
ON candidates(rule_id);

CREATE INDEX idx_candidate_legs_candidate
ON candidate_legs(candidate_id);

CREATE INDEX idx_candidate_legs_quote
ON candidate_legs(option_quote_id);

CREATE INDEX idx_candidate_controls_candidate
ON candidate_controls(candidate_id);

CREATE INDEX idx_candidate_controls_quote
ON candidate_controls(control_quote_id);


-- =====================================================================
-- RESEARCH INTEGRITY
-- =====================================================================

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


-- =====================================================================
-- IMMUTABILITY
-- =====================================================================

CREATE TRIGGER trg_market_snapshots_no_update
BEFORE UPDATE
ON market_snapshots
BEGIN
    SELECT RAISE(
        ABORT,
        'Market snapshots are immutable evidence.'
    );
END;


CREATE TRIGGER trg_market_snapshots_no_delete
BEFORE DELETE
ON market_snapshots
BEGIN
    SELECT RAISE(
        ABORT,
        'Market snapshots cannot be deleted.'
    );
END;


CREATE TRIGGER trg_option_quotes_no_update
BEFORE UPDATE
ON option_quotes
BEGIN
    SELECT RAISE(
        ABORT,
        'Option quotes are immutable evidence.'
    );
END;


CREATE TRIGGER trg_option_quotes_no_delete
BEFORE DELETE
ON option_quotes
BEGIN
    SELECT RAISE(
        ABORT,
        'Option quotes cannot be deleted.'
    );
END;


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


CREATE TRIGGER trg_candidate_legs_no_update
BEFORE UPDATE
ON candidate_legs
BEGIN
    SELECT RAISE(
        ABORT,
        'Candidate legs are immutable.'
    );
END;


CREATE TRIGGER trg_candidate_legs_no_delete
BEFORE DELETE
ON candidate_legs
BEGIN
    SELECT RAISE(
        ABORT,
        'Candidate legs cannot be deleted.'
    );
END;


CREATE TRIGGER trg_candidate_controls_no_update
BEFORE UPDATE
ON candidate_controls
BEGIN
    SELECT RAISE(
        ABORT,
        'Matched controls are immutable.'
    );
END;


CREATE TRIGGER trg_candidate_controls_no_delete
BEFORE DELETE
ON candidate_controls
BEGIN
    SELECT RAISE(
        ABORT,
        'Matched controls cannot be deleted.'
    );
END;


-- =====================================================================
-- SCHEMA VERSION
-- =====================================================================

INSERT INTO schema_version (
    version,
    applied_at
)
VALUES (
    4,
    strftime(
        '%Y-%m-%dT%H:%M:%SZ',
        'now'
    )
);

COMMIT;