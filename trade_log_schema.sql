-- =====================================================================
-- Christiania — schema v4
--
-- Design rules:
--   1. Original prediction evidence is immutable.
--   2. Entry market evidence is immutable.
--   3. Paper/live provenance is immutable.
--   4. Annotations are append-only.
--   5. Rejected decisions are recorded.
--   6. Bad records are preserved by voiding rather than deleting.
--
-- Conventions:
--   * Timestamps: ISO-8601 UTC strings.
--   * Prices/Greeks/IV: REAL.
--   * Cash/fees/max loss: INTEGER minor currency units.
--   * Probabilities: REAL in [0,1].
-- =====================================================================

PRAGMA foreign_keys = ON;


-- =====================================================================
-- SCHEMA VERSION
-- =====================================================================

CREATE TABLE schema_version (
    version     INTEGER NOT NULL,
    applied_at  TEXT    NOT NULL
);

INSERT INTO schema_version (
    version,
    applied_at
)
VALUES (
    4,
    strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
);


-- =====================================================================
-- TRADES
-- =====================================================================

CREATE TABLE trades (
    id                      INTEGER PRIMARY KEY,

    -- Provenance
    created_at              TEXT    NOT NULL,
    underlying              TEXT    NOT NULL,
    currency                TEXT    NOT NULL DEFAULT 'USD',
    is_paper                INTEGER NOT NULL DEFAULT 1,

    status                  TEXT    NOT NULL DEFAULT 'OPEN',
    parent_trade_id         INTEGER REFERENCES trades(id),
    strategy                TEXT,

    -- Entry evidence
    entry_at                TEXT,
    entry_underlying        REAL,
    entry_fx_rate           REAL,
    entry_fees              INTEGER,
    entry_cash              INTEGER,

    -- Volatility / event evidence
    entry_iv_rank           REAL,
    next_earnings_date      TEXT,

    -- Prediction
    thesis                  TEXT    NOT NULL,
    prediction              TEXT    NOT NULL,
    horizon_date            TEXT    NOT NULL,

    p_thesis_initial        REAL    NOT NULL,
    p_thesis                REAL    NOT NULL,
    p_profit                REAL    NOT NULL,

    invalidation            TEXT    NOT NULL,

    -- Risk plan
    max_loss                INTEGER NOT NULL,
    profit_target           TEXT    NOT NULL,
    stop_condition          TEXT    NOT NULL,

    -- Rejection / voiding
    rejection_reason        TEXT,
    voided_at               TEXT,
    void_reason             TEXT,

    -- Exit
    exit_at                 TEXT,
    exit_underlying         REAL,
    exit_fx_rate            REAL,
    exit_fees               INTEGER,
    exit_cash               INTEGER,
    exit_reason             TEXT,

    -- Resolution
    thesis_correct          INTEGER,
    was_profitable          INTEGER,
    resolved_at             TEXT,

    CHECK (
        status IN (
            'OPEN',
            'CLOSED',
            'EXPIRED',
            'ASSIGNED',
            'ROLLED',
            'REJECTED',
            'VOIDED'
        )
    ),

    CHECK (
        is_paper IN (0,1)
    ),

    CHECK (
        p_thesis_initial >= 0.0
        AND p_thesis_initial <= 1.0
    ),

    CHECK (
        p_thesis >= 0.0
        AND p_thesis <= 1.0
    ),

    CHECK (
        p_profit >= 0.0
        AND p_profit <= 1.0
    ),

    CHECK (
        entry_iv_rank IS NULL
        OR (
            entry_iv_rank >= 0.0
            AND entry_iv_rank <= 100.0
        )
    ),

    CHECK (
        max_loss >= 0
    ),

    CHECK (
        entry_fees IS NULL
        OR entry_fees >= 0
    ),

    CHECK (
        exit_fees IS NULL
        OR exit_fees >= 0
    ),

    CHECK (
        thesis_correct IS NULL
        OR thesis_correct IN (0,1)
    ),

    CHECK (
        was_profitable IS NULL
        OR was_profitable IN (0,1)
    ),

    CHECK (
        length(trim(thesis)) > 0
    ),

    CHECK (
        length(trim(prediction)) > 0
    ),

    CHECK (
        length(trim(invalidation)) > 0
    ),

    -- -------------------------------------------------------------
    -- Decision-state integrity
    -- -------------------------------------------------------------

    CHECK (
        (
            status = 'REJECTED'

            AND entry_at IS NULL
            AND entry_underlying IS NULL
            AND entry_fx_rate IS NULL
            AND entry_fees IS NULL
            AND entry_cash IS NULL

            AND rejection_reason IS NOT NULL
            AND length(trim(rejection_reason)) > 0

            AND voided_at IS NULL
            AND void_reason IS NULL
        )

        OR

        (
            status = 'VOIDED'

            AND voided_at IS NOT NULL

            AND void_reason IS NOT NULL
            AND length(trim(void_reason)) > 0
        )

        OR

        (
            status NOT IN (
                'REJECTED',
                'VOIDED'
            )

            AND entry_at IS NOT NULL
            AND entry_underlying IS NOT NULL

            AND entry_fx_rate IS NOT NULL
            AND entry_fx_rate > 0

            AND entry_fees IS NOT NULL
            AND entry_cash IS NOT NULL

            AND rejection_reason IS NULL

            AND voided_at IS NULL
            AND void_reason IS NULL
        )
    ),

    -- -------------------------------------------------------------
    -- Exit-state integrity
    -- -------------------------------------------------------------

    CHECK (
        (
            status = 'OPEN'

            AND exit_at IS NULL
            AND exit_underlying IS NULL
            AND exit_fx_rate IS NULL
            AND exit_fees IS NULL
            AND exit_cash IS NULL
            AND exit_reason IS NULL
        )

        OR

        (
            status IN (
                'CLOSED',
                'EXPIRED',
                'ASSIGNED',
                'ROLLED'
            )

            AND exit_at IS NOT NULL
            AND exit_underlying IS NOT NULL

            AND exit_fx_rate IS NOT NULL
            AND exit_fx_rate > 0

            AND exit_fees IS NOT NULL
            AND exit_cash IS NOT NULL

            AND exit_reason IS NOT NULL
            AND length(trim(exit_reason)) > 0
        )

        OR

        (
            status = 'REJECTED'

            AND exit_at IS NULL
            AND exit_underlying IS NULL
            AND exit_fx_rate IS NULL
            AND exit_fees IS NULL
            AND exit_cash IS NULL
            AND exit_reason IS NULL
        )

        OR

        (
            status = 'VOIDED'
        )
    ),

    -- -------------------------------------------------------------
    -- Resolution-state integrity
    -- -------------------------------------------------------------

    CHECK (
        (
            resolved_at IS NULL
            AND thesis_correct IS NULL
            AND was_profitable IS NULL
        )

        OR

        (
            resolved_at IS NOT NULL
            AND thesis_correct IS NOT NULL

            AND (
                (
                    status = 'REJECTED'
                    AND was_profitable IS NULL
                )

                OR

                (
                    status IN (
                        'CLOSED',
                        'EXPIRED',
                        'ASSIGNED',
                        'ROLLED'
                    )

                    AND was_profitable IS NOT NULL
                )
            )
        )
    )
);


CREATE INDEX idx_trades_status
ON trades(status);

CREATE INDEX idx_trades_underlying
ON trades(underlying);

CREATE INDEX idx_trades_entry_at
ON trades(entry_at);

CREATE INDEX idx_trades_parent
ON trades(parent_trade_id);

CREATE INDEX idx_trades_paper
ON trades(is_paper);


-- =====================================================================
-- TRADE LEGS
-- =====================================================================

CREATE TABLE trade_legs (
    id                  INTEGER PRIMARY KEY,

    trade_id            INTEGER NOT NULL
                        REFERENCES trades(id)
                        ON DELETE CASCADE,

    leg_no              INTEGER NOT NULL,

    right               TEXT    NOT NULL,
    direction           TEXT    NOT NULL,

    strike              REAL    NOT NULL,
    expiration          TEXT    NOT NULL,

    contracts           INTEGER NOT NULL,
    multiplier          INTEGER NOT NULL DEFAULT 100,

    -- Market evidence at entry
    entry_quote_at      TEXT,
    entry_iv            REAL,
    entry_delta         REAL,

    entry_bid           REAL    NOT NULL,
    entry_ask           REAL    NOT NULL,
    entry_fill          REAL    NOT NULL,

    -- Exit evidence
    exit_bid            REAL,
    exit_ask            REAL,
    exit_fill           REAL,

    UNIQUE (
        trade_id,
        leg_no
    ),

    CHECK (
        right IN (
            'C',
            'P'
        )
    ),

    CHECK (
        direction IN (
            'BUY',
            'SELL'
        )
    ),

    CHECK (
        contracts > 0
    ),

    CHECK (
        multiplier > 0
    ),

    CHECK (
        strike > 0
    ),

    CHECK (
        entry_bid >= 0
    ),

    CHECK (
        entry_ask >= 0
    ),

    CHECK (
        entry_fill >= 0
    ),

    CHECK (
        entry_ask >= entry_bid
    ),

    CHECK (
        entry_iv IS NULL
        OR entry_iv >= 0.0
    ),

    CHECK (
        entry_delta IS NULL
        OR (
            entry_delta >= -1.0
            AND entry_delta <= 1.0
        )
    ),

    CHECK (
        exit_ask IS NULL
        OR exit_bid IS NULL
        OR exit_ask >= exit_bid
    )
);


CREATE INDEX idx_legs_trade
ON trade_legs(trade_id);


-- =====================================================================
-- ANNOTATIONS
-- =====================================================================

CREATE TABLE annotations (
    id          INTEGER PRIMARY KEY,

    trade_id    INTEGER NOT NULL
                REFERENCES trades(id)
                ON DELETE CASCADE,

    created_at  TEXT    NOT NULL,
    body        TEXT    NOT NULL,

    CHECK (
        length(trim(body)) > 0
    )
);


CREATE INDEX idx_annotations_trade
ON annotations(trade_id);


-- =====================================================================
-- IMMUTABILITY TRIGGERS
-- =====================================================================


-- ---------------------------------------------------------------------
-- Prediction + risk fields
-- ---------------------------------------------------------------------

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


-- ---------------------------------------------------------------------
-- Entry/provenance evidence
-- ---------------------------------------------------------------------

CREATE TRIGGER trg_trades_entry_immutable
BEFORE UPDATE OF
    created_at,
    entry_at,
    entry_underlying,
    entry_fx_rate,
    entry_fees,
    entry_cash,
    entry_iv_rank,
    next_earnings_date,
    underlying,
    currency,
    is_paper,
    parent_trade_id,
    strategy,
    rejection_reason
ON trades
BEGIN
    SELECT RAISE(
        ABORT,
        'Entry data is immutable. Void the row and preserve the original evidence.'
    );
END;


-- ---------------------------------------------------------------------
-- Resolution write-once
-- ---------------------------------------------------------------------

CREATE TRIGGER trg_trades_resolution_write_once
BEFORE UPDATE OF
    thesis_correct,
    was_profitable,
    resolved_at
ON trades
WHEN OLD.resolved_at IS NOT NULL
BEGIN
    SELECT RAISE(
        ABORT,
        'This trade is already resolved. Add an annotation instead.'
    );
END;


-- ---------------------------------------------------------------------
-- Leg entry evidence
-- ---------------------------------------------------------------------

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


-- ---------------------------------------------------------------------
-- Append-only annotations
-- ---------------------------------------------------------------------

CREATE TRIGGER trg_annotations_no_update
BEFORE UPDATE
ON annotations
BEGIN
    SELECT RAISE(
        ABORT,
        'Annotations are append-only.'
    );
END;


CREATE TRIGGER trg_annotations_no_delete
BEFORE DELETE
ON annotations
BEGIN
    SELECT RAISE(
        ABORT,
        'Annotations are append-only.'
    );
END;


-- ---------------------------------------------------------------------
-- Audit records cannot be physically deleted
-- ---------------------------------------------------------------------

CREATE TRIGGER trg_trades_no_delete
BEFORE DELETE
ON trades
BEGIN
    SELECT RAISE(
        ABORT,
        'Trades cannot be deleted. Mark an invalid record VOIDED.'
    );
END;


CREATE TRIGGER trg_legs_no_delete
BEFORE DELETE
ON trade_legs
BEGIN
    SELECT RAISE(
        ABORT,
        'Trade legs cannot be deleted.'
    );
END;


-- ---------------------------------------------------------------------
-- Terminal lifecycle states cannot be rewritten
-- ---------------------------------------------------------------------

CREATE TRIGGER trg_status_terminal
BEFORE UPDATE OF status
ON trades
WHEN
    OLD.status <> NEW.status
    AND OLD.status <> 'OPEN'
BEGIN
    SELECT RAISE(
        ABORT,
        'Only OPEN trades may transition to another status.'
    );
END;


-- ---------------------------------------------------------------------
-- Voiding is one-way
-- ---------------------------------------------------------------------

CREATE TRIGGER trg_void_write_once
BEFORE UPDATE OF
    voided_at,
    void_reason
ON trades
WHEN OLD.voided_at IS NOT NULL
BEGIN
    SELECT RAISE(
        ABORT,
        'A voided trade is already locked.'
    );
END;


-- ---------------------------------------------------------------------
-- Rejected/voided decisions cannot acquire legs
-- ---------------------------------------------------------------------

CREATE TRIGGER trg_no_legs_on_rejected
BEFORE INSERT
ON trade_legs
WHEN (
    SELECT status
    FROM trades
    WHERE id = NEW.trade_id
) IN (
    'REJECTED',
    'VOIDED'
)
BEGIN
    SELECT RAISE(
        ABORT,
        'A rejected or voided decision cannot acquire new legs.'
    );
END;


-- =====================================================================
-- VIEWS
-- =====================================================================


-- ---------------------------------------------------------------------
-- Open positions
-- ---------------------------------------------------------------------

CREATE VIEW v_open_positions AS
SELECT
    t.id,
    t.underlying,
    t.strategy,
    t.is_paper,
    t.entry_at,
    t.horizon_date,
    t.p_thesis,
    t.p_profit,
    t.entry_iv_rank,
    t.max_loss,

    COUNT(l.id) AS legs,

    MIN(
        l.expiration
    ) AS nearest_expiry,

    CAST(
        julianday(
            MIN(l.expiration)
        )
        - julianday('now')
        AS INTEGER
    ) AS dte

FROM trades t

LEFT JOIN trade_legs l
    ON l.trade_id = t.id

WHERE t.status = 'OPEN'

GROUP BY t.id;


-- ---------------------------------------------------------------------
-- Realized P&L
-- ---------------------------------------------------------------------

CREATE VIEW v_realized_pnl AS
SELECT
    t.id,
    t.underlying,
    t.currency,
    t.is_paper,
    t.entry_at,
    t.exit_at,
    t.exit_reason,

    (
        COALESCE(
            t.entry_cash,
            0
        )
        +
        COALESCE(
            t.exit_cash,
            0
        )
        -
        COALESCE(
            t.entry_fees,
            0
        )
        -
        COALESCE(
            t.exit_fees,
            0
        )
    ) AS pnl_minor,

    t.thesis_correct,
    t.was_profitable

FROM trades t

WHERE t.status IN (
    'CLOSED',
    'EXPIRED',
    'ASSIGNED',
    'ROLLED'
);


-- ---------------------------------------------------------------------
-- Slippage
-- ---------------------------------------------------------------------

CREATE VIEW v_slippage AS
SELECT
    l.trade_id,
    l.leg_no,
    l.direction,

    l.entry_quote_at,

    (
        l.entry_bid
        + l.entry_ask
    ) / 2.0 AS entry_mid,

    CASE
        WHEN l.direction = 'BUY'
        THEN
            l.entry_fill
            -
            (
                l.entry_bid
                + l.entry_ask
            ) / 2.0

        ELSE
            (
                l.entry_bid
                + l.entry_ask
            ) / 2.0
            - l.entry_fill
    END AS entry_slip,

    CASE
        WHEN l.exit_fill IS NULL
        THEN NULL

        WHEN l.direction = 'BUY'
        THEN
            (
                l.exit_bid
                + l.exit_ask
            ) / 2.0
            - l.exit_fill

        ELSE
            l.exit_fill
            -
            (
                l.exit_bid
                + l.exit_ask
            ) / 2.0
    END AS exit_slip,

    (
        l.entry_ask
        - l.entry_bid
    )
    /
    NULLIF(
        (
            l.entry_bid
            + l.entry_ask
        ) / 2.0,
        0
    ) AS entry_spread_pct

FROM trade_legs l;


-- ---------------------------------------------------------------------
-- Calibration
--
-- Paper/live is exposed explicitly so calibration can be separated.
-- ---------------------------------------------------------------------

CREATE VIEW v_calibration AS

SELECT
    id,
    resolved_at,
    status,
    is_paper,

    'THESIS' AS question,

    p_thesis AS p,
    thesis_correct AS outcome,

    (
        p_thesis
        - thesis_correct
    )
    *
    (
        p_thesis
        - thesis_correct
    ) AS brier

FROM trades

WHERE thesis_correct IS NOT NULL


UNION ALL


SELECT
    id,
    resolved_at,
    status,
    is_paper,

    'PROFIT' AS question,

    p_profit AS p,
    was_profitable AS outcome,

    (
        p_profit
        - was_profitable
    )
    *
    (
        p_profit
        - was_profitable
    ) AS brier

FROM trades

WHERE was_profitable IS NOT NULL;


-- ---------------------------------------------------------------------
-- Calibration buckets
-- ---------------------------------------------------------------------

CREATE VIEW v_calibration_buckets AS
SELECT
    question,
    is_paper,

    MIN(
        CAST(
            p * 10
            AS INTEGER
        ),
        9
    ) AS bucket,

    COUNT(*) AS n,

    ROUND(
        AVG(p),
        3
    ) AS mean_p,

    ROUND(
        AVG(outcome),
        3
    ) AS hit_rate,

    ROUND(
        AVG(brier),
        4
    ) AS mean_brier

FROM v_calibration

GROUP BY
    question,
    is_paper,
    bucket;


-- =====================================================================
-- CHRISTIANIA RESEARCH LAYER
--
-- Native schema v4 includes:
--   market_snapshots
--   option_quotes
--   candidates
--   candidate_legs
--   candidate_controls
--
-- Historical installations receive these through migration 004.
-- Fresh installations create them directly below.
-- =====================================================================

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
