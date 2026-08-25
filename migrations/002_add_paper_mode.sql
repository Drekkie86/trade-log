PRAGMA foreign_keys = ON;

BEGIN TRANSACTION;

-- ---------------------------------------------------------
-- v2: distinguish paper decisions from live trades
-- ---------------------------------------------------------

ALTER TABLE trades
ADD COLUMN is_paper INTEGER NOT NULL DEFAULT 1
CHECK (is_paper IN (0, 1));


-- ---------------------------------------------------------
-- Paper/live status is provenance and must be immutable.
-- Recreate the existing entry/provenance trigger with
-- is_paper included.
-- ---------------------------------------------------------

DROP TRIGGER IF EXISTS trg_trades_entry_immutable;

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


-- ---------------------------------------------------------
-- Record migration
-- ---------------------------------------------------------

INSERT INTO schema_version (
    version,
    applied_at
)
VALUES (
    2,
    strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
);

COMMIT;