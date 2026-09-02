-- =====================================================================
-- Christiania — migration 015
--
-- Scanner join performance.
--
-- hypothesis_scanner.py's _load_reference_and_iv() joins option_quotes ->
-- market_snapshots -> listing_reference_contracts on six columns
-- (research_run_id, provider, underlying, expiration, strike, right), but
-- the only index available, idx_listing_reference_identity, covers just
-- four of them (underlying, expiration, strike, right). EXPLAIN QUERY PLAN
-- confirms every match still requires a post-lookup filter on
-- research_run_id and provider, and that cost grows as more historical
-- runs accumulate overlapping (underlying, expiration, strike, right)
-- identities in the reference table.
--
-- This migration adds the missing composite covering index. It does not
-- replace idx_listing_reference_identity or idx_listing_reference_run;
-- both remain valid for other query shapes and are left untouched.
-- =====================================================================

PRAGMA foreign_keys = ON;

CREATE INDEX idx_listing_reference_scanner_join
ON listing_reference_contracts(
    research_run_id,
    provider,
    underlying,
    expiration,
    strike,
    right
);

INSERT INTO schema_version (
    version,
    applied_at
)
SELECT
    15,
    strftime(
        '%Y-%m-%dT%H:%M:%SZ',
        'now'
    )
WHERE NOT EXISTS (
    SELECT 1
    FROM schema_version
    WHERE version = 15
);
