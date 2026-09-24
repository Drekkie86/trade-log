-- =====================================================================
-- Christiania — migration 034
--
-- Storage V2D foundation: parent-delete foreign-key support indexes.
--
-- SQLite parent deletes probe every child foreign key. A child-side index
-- must begin with the FK columns or a large parent delete can degrade into
-- repeated full scans. V2C deletes listing_reference_contracts and
-- option_quotes, so every FK into those parent tables is required to have a
-- leading support index before destructive pruning is eligible.
-- =====================================================================
PRAGMA foreign_keys = ON;

CREATE INDEX IF NOT EXISTS idx_shadow_candidates_reference_contract
ON shadow_candidates(reference_contract_id);

CREATE INDEX IF NOT EXISTS idx_shadow_candidates_entry_quote_observation
ON shadow_candidates(entry_quote_observation_id);

CREATE INDEX IF NOT EXISTS idx_shadow_candidates_entry_greek_observation
ON shadow_candidates(entry_greek_observation_id);

CREATE INDEX IF NOT EXISTS idx_hypothesis_scanner_evaluations_reference_contract
ON hypothesis_scanner_evaluations(reference_contract_id);

CREATE INDEX IF NOT EXISTS idx_hypothesis_scanner_evaluations_option_quote
ON hypothesis_scanner_evaluations(option_quote_id);

CREATE INDEX IF NOT EXISTS idx_surface_v2_reference_contract
ON local_surface_residual_v2_observations(reference_contract_id);

INSERT INTO schema_version(version, applied_at)
SELECT 34, strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
WHERE NOT EXISTS (
    SELECT 1
    FROM schema_version
    WHERE version = 34
);
