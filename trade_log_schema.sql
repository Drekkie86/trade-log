-- =====================================================================
-- Trade Log — schema v2
--
-- Design rules this schema enforces at the database level:
--   1. Prediction fields are write-once. Triggers reject any UPDATE.
--   2. Entry market data is evidence, not editable state. Same treatment.
--   3. Annotations are append-only. No UPDATE, no DELETE.
--   4. Rejected trades are first-class rows, so the log is not a
--      survivorship-biased record of only the trades that were taken.
--
-- Conventions:
--   * All timestamps are ISO-8601 UTC strings ('2026-08-24T14:33:07Z').
--   * Per-share prices (strikes, bids, asks, fills, underlying) are REAL.
--   * Realized cash amounts (fees, debits, proceeds) are INTEGER minor
--     units of `currency` — i.e. US cents for USD. Avoids float drift on
--     anything that has to reconcile against a broker statement.
--   * Probabilities are REAL in [0, 1], not percentages.
-- =====================================================================

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------
-- schema_version — so future migrations have something to check against
-- ---------------------------------------------------------------------
CREATE TABLE schema_version (
    version     INTEGER NOT NULL,
    applied_at  TEXT    NOT NULL
);

INSERT INTO schema_version (version, applied_at)
VALUES (2, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'));


-- ---------------------------------------------------------------------
-- trades
--
-- One row per decision — including decisions NOT to trade (status
-- 'REJECTED'), which carry a full thesis and probabilities but no legs.
-- ---------------------------------------------------------------------
CREATE TABLE trades (
    id                    INTEGER PRIMARY KEY,

    -- Provenance -----------------------------------------------------
    created_at            TEXT    NOT NULL,   -- when the row was written
    underlying            TEXT    NOT NULL,   -- ticker, e.g. 'META'
    currency              TEXT    NOT NULL DEFAULT 'USD',
    is_paper              INTEGER NOT NULL DEFAULT 1, -- 1 = paper, 0 = live

    status                TEXT    NOT NULL DEFAULT 'OPEN',
    parent_trade_id       INTEGER REFERENCES trades(id), -- set on a roll
    strategy              TEXT,              -- 'LONG_CALL', 'DEBIT_SPREAD', ...

    -- Entry: market state at the moment of fill ----------------------
    -- NULL for REJECTED rows. Immutable once written.
    entry_at              TEXT,              -- fill time, not record time
    entry_underlying      REAL,
    entry_fx_rate         REAL,              -- currency -> EUR at fill
    entry_fees            INTEGER,           -- minor units, >= 0
    entry_cash            INTEGER,           -- net cash flow, minor units
                                             -- negative = debit paid

    -- Prediction: written once, never revised ------------------------
    thesis                TEXT    NOT NULL,  -- why this trade
    prediction            TEXT    NOT NULL,  -- what specifically happens
    horizon_date          TEXT    NOT NULL,  -- by when
    p_thesis              REAL    NOT NULL,  -- P(prediction comes true)
    p_profit              REAL    NOT NULL,  -- P(trade closes profitable)
    invalidation          TEXT    NOT NULL,  -- what proves me wrong

    -- Risk plan: written once ----------------------------------------
    max_loss              INTEGER NOT NULL,  -- minor units, >= 0
    profit_target         TEXT    NOT NULL,
    stop_condition        TEXT    NOT NULL,

    -- Rejection / voiding --------------------------------------------
    rejection_reason      TEXT,              -- required iff REJECTED
    voided_at             TEXT,              -- set when preserving a bad row
    void_reason           TEXT,              -- required iff VOIDED

    -- Exit: mutable, written at close --------------------------------
    exit_at               TEXT,
    exit_underlying       REAL,
    exit_fx_rate          REAL,
    exit_fees             INTEGER,
    exit_cash             INTEGER,           -- positive = proceeds
    exit_reason           TEXT,              -- 'TARGET','STOP','INVALIDATED',
                                             -- 'EXPIRY','ROLL','DISCRETIONARY'

    -- Resolution: the two questions, scored separately ---------------
    thesis_correct        INTEGER,           -- 0/1, set at resolution
    was_profitable        INTEGER,           -- 0/1, NULL for REJECTED
    resolved_at           TEXT,

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

    CHECK (is_paper IN (0,1)),
    CHECK (p_thesis >= 0.0 AND p_thesis <= 1.0),
    CHECK (p_profit >= 0.0 AND p_profit <= 1.0),
    CHECK (max_loss >= 0),
    CHECK (entry_fees IS NULL OR entry_fees >= 0),
    CHECK (exit_fees IS NULL OR exit_fees >= 0),
    CHECK (thesis_correct IS NULL OR thesis_correct IN (0,1)),
    CHECK (was_profitable IS NULL OR was_profitable IN (0,1)),
    CHECK (length(trim(thesis)) > 0),
    CHECK (length(trim(prediction)) > 0),
    CHECK (length(trim(invalidation)) > 0),

    -- Decision-state integrity.
    CHECK (
        (
            status = 'REJECTED'
            AND entry_at IS NULL
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
            status NOT IN ('REJECTED','VOIDED')
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

    -- Exit-state integrity.
    -- Closed outcomes must have complete trade-level exit evidence.
    -- OPEN/REJECTED rows must have none.
    -- VOIDED rows preserve whatever evidence existed before they were voided.
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
            status IN ('CLOSED','EXPIRED','ASSIGNED','ROLLED')
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

    -- Resolution-state integrity.
    -- Resolution is all-or-nothing.
    -- Rejected decisions resolve the thesis only;
    -- traded decisions resolve both.
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


-- ---------------------------------------------------------------------
-- trade_legs
--
-- One row per contract leg. Single-leg trades have exactly one row.
-- Bid and ask are stored at entry AND exit so slippage against mid is
-- computable on both sides — the exit fill is usually the worse one.
-- ---------------------------------------------------------------------
CREATE TABLE trade_legs (
    id              INTEGER PRIMARY KEY,

    trade_id        INTEGER NOT NULL
                    REFERENCES trades(id)
                    ON DELETE CASCADE,

    leg_no          INTEGER NOT NULL,

    right           TEXT    NOT NULL, -- 'C' or 'P'
    direction       TEXT    NOT NULL, -- 'BUY' or 'SELL'
    strike          REAL    NOT NULL,
    expiration      TEXT    NOT NULL, -- 'YYYY-MM-DD'
    contracts       INTEGER NOT NULL,
    multiplier      INTEGER NOT NULL DEFAULT 100,

    entry_bid       REAL    NOT NULL,
    entry_ask       REAL    NOT NULL,
    entry_fill      REAL    NOT NULL, -- what you actually got

    exit_bid        REAL,
    exit_ask        REAL,
    exit_fill       REAL,

    UNIQUE (trade_id, leg_no),

    CHECK (right IN ('C','P')),
    CHECK (direction IN ('BUY','SELL')),
    CHECK (contracts > 0),
    CHECK (strike > 0),
    CHECK (entry_ask >= entry_bid),

    CHECK (
        exit_ask IS NULL
        OR exit_bid IS NULL
        OR exit_ask >= exit_bid
    )
);

CREATE INDEX idx_legs_trade
ON trade_legs(trade_id);


-- ---------------------------------------------------------------------
-- annotations
--
-- Append-only. Later thinking lives here, never in prediction fields.
-- ---------------------------------------------------------------------
CREATE TABLE annotations (
    id          INTEGER PRIMARY KEY,

    trade_id    INTEGER NOT NULL
                REFERENCES trades(id)
                ON DELETE CASCADE,

    created_at  TEXT    NOT NULL,
    body        TEXT    NOT NULL,

    CHECK (length(trim(body)) > 0)
);

CREATE INDEX idx_annotations_trade
ON annotations(trade_id);


-- =====================================================================
-- IMMUTABILITY TRIGGERS
--
-- SQLite has no column-level permissions, so this is what actually
-- stops hindsight from rewriting the record.
--
-- A trigger fires on UPDATE OF the listed columns whether or not the
-- value changed, so the app must never include these columns in a
-- blanket UPDATE statement.
-- =====================================================================


-- ---------------------------------------------------------------------
-- Prediction and risk plan: fixed at entry.
-- ---------------------------------------------------------------------
CREATE TRIGGER trg_trades_prediction_immutable
BEFORE UPDATE OF
    thesis,
    prediction,
    horizon_date,
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
-- Entry market data and provenance: evidence, not editable state.
--
-- is_paper belongs here deliberately: a paper trade may never later
-- be relabelled as a real trade (or vice versa).
-- ---------------------------------------------------------------------
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
-- Resolution can be set once, then locked.
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
-- Leg entry data: same evidence rule as trade entry data.
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
-- Annotations are append-only.
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
-- Trades and legs are audit evidence: never physically delete them.
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
-- Once a trade has left OPEN, its lifecycle state cannot be rewritten.
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
-- Voiding is one-way audit action and must carry timestamp + reason.
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
-- Rejected / voided decisions cannot acquire new legs.
-- ---------------------------------------------------------------------
CREATE TRIGGER trg_no_legs_on_rejected
BEFORE INSERT
ON trade_legs
WHEN (
    SELECT status
    FROM trades
    WHERE id = NEW.trade_id
) IN ('REJECTED','VOIDED')
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
-- Open positions with leg count and days to nearest expiry.
-- ---------------------------------------------------------------------
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

    COUNT(l.id) AS legs,

    MIN(l.expiration) AS nearest_expiry,

    CAST(
        julianday(MIN(l.expiration))
        - julianday('now')
        AS INTEGER
    ) AS dte

FROM trades t

LEFT JOIN trade_legs l
    ON l.trade_id = t.id

WHERE t.status = 'OPEN'

GROUP BY t.id;


-- ---------------------------------------------------------------------
-- Realized P&L, net of fees, in minor units.
-- ---------------------------------------------------------------------
CREATE VIEW v_realized_pnl AS
SELECT
    t.id,
    t.underlying,
    t.currency,
    t.entry_at,
    t.exit_at,
    t.exit_reason,

    (
        COALESCE(t.entry_cash, 0)
        + COALESCE(t.exit_cash, 0)
        - COALESCE(t.entry_fees, 0)
        - COALESCE(t.exit_fees, 0)
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
-- Slippage against mid, per leg, both sides.
--
-- Positive = execution cost.
-- Buys cost you when fill > mid.
-- Sells cost you when fill < mid.
-- ---------------------------------------------------------------------
CREATE VIEW v_slippage AS
SELECT
    l.trade_id,
    l.leg_no,
    l.direction,

    (
        l.entry_bid
        + l.entry_ask
    ) / 2.0 AS entry_mid,

    CASE
        WHEN l.direction = 'BUY'
        THEN
            l.entry_fill
            - (
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
            - (
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
-- Calibration input.
--
-- One row per resolved decision, per question.
-- THESIS rows include rejected decisions.
-- PROFIT rows cannot.
-- ---------------------------------------------------------------------
CREATE VIEW v_calibration AS

SELECT
    id,
    resolved_at,
    status,
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
-- Calibration by decile bucket.
--
-- With single-digit n this is noise.
-- The view exists so the shape is ready once the sample becomes useful.
--
-- MIN(..., 9) ensures a prediction of exactly 1.0 lands in bucket 9,
-- rather than accidentally creating bucket 10.
-- ---------------------------------------------------------------------
CREATE VIEW v_calibration_buckets AS
SELECT
    question,

    MIN(
        CAST(p * 10 AS INTEGER),
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
    bucket;