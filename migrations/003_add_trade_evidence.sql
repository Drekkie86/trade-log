PRAGMA foreign_keys = ON;

BEGIN TRANSACTION;

-- ============================================================
-- Schema v3
--
-- Adds:
--   trades.p_thesis_initial
--   trades.entry_iv_rank
--   trades.next_earnings_date
--
--   trade_legs.entry_quote_at
--   trade_legs.entry_iv
--   trade_legs.entry_delta
-- ============================================================


ALTER TABLE trades
ADD COLUMN p_thesis_initial REAL;

ALTER TABLE trades
ADD COLUMN entry_iv_rank REAL;

ALTER TABLE trades
ADD COLUMN next_earnings_date TEXT;


-- Existing rows pre-date the distinction between initial and
-- final thesis probability. The only defensible historical
-- value is the p_thesis value that was actually recorded.
UPDATE trades
SET p_thesis_initial = p_thesis
WHERE p_thesis_initial IS NULL;


ALTER TABLE trade_legs
ADD COLUMN entry_quote_at TEXT;

ALTER TABLE trade_legs
ADD COLUMN entry_iv REAL;

ALTER TABLE trade_legs
ADD COLUMN entry_delta REAL;


-- ------------------------------------------------------------
-- Rebuild prediction immutability trigger.
-- ------------------------------------------------------------

DROP TRIGGER IF EXISTS trg_trades_prediction_immutable;

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


-- ------------------------------------------------------------
-- Rebuild leg entry immutability trigger.
-- ------------------------------------------------------------

DROP TRIGGER IF EXISTS trg_legs_entry_immutable;

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


-- ------------------------------------------------------------
-- Record migration.
-- ------------------------------------------------------------

INSERT INTO schema_version (
    version,
    applied_at
)
VALUES (
    3,
    strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
);

COMMIT;