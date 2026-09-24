-- =====================================================================
-- Christiania — migration 034
--
-- Storage V2C foreign-key delete support indexes.
--
-- SQLite checks child tables when a referenced parent row is deleted.
-- Parent pruning of listing_reference_contracts and option_quotes therefore
-- requires a child-side index whose leading column(s) match every relevant
-- foreign key. Without these indexes a million-row parent delete can degrade
-- into repeated full scans of large evidence tables.
--
-- These indexes do not change evidence semantics. They only make the
-- existing referential-integrity checks bounded/indexed.
-- =====================================================================
PRAGMA foreign_keys = ON;

CREATE INDEX idx_shadow_candidates_reference_contract
ON shadow_candidates(reference_contract_id);

CREATE INDEX idx_hypothesis_scanner_evaluations_reference
ON hypothesis_scanner_evaluations(reference_contract_id);

CREATE INDEX idx_hypothesis_scanner_evaluations_quote
ON hypothesis_scanner_evaluations(option_quote_id);

CREATE INDEX idx_surface_v2_reference
ON local_surface_residual_v2_observations(reference_contract_id);

INSERT INTO schema_version(version, applied_at)
SELECT
    34,
    strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
WHERE NOT EXISTS (
    SELECT 1
    FROM schema_version
    WHERE version = 34
);
