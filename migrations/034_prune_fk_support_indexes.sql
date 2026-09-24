-- =====================================================================
-- Christiania — migration 034
--
-- Storage / historical research reliability hardening.
--
-- SQLite validates child foreign keys during parent DELETE. Every child-side
-- foreign-key column that points at the two high-volume V2C parent families
-- must therefore have a leading index; otherwise deleting one parent row can
-- force a full scan of the child table.
--
-- This migration adds only the four support indexes proven missing by the
-- schema-wide FK audit. It changes no evidence semantics and deletes no data.
-- =====================================================================
PRAGMA foreign_keys = ON;

CREATE INDEX idx_shadow_candidates_reference_contract
ON shadow_candidates(reference_contract_id);

CREATE INDEX idx_hypothesis_scanner_evaluations_reference_contract
ON hypothesis_scanner_evaluations(reference_contract_id);

CREATE INDEX idx_hypothesis_scanner_evaluations_option_quote
ON hypothesis_scanner_evaluations(option_quote_id);

CREATE INDEX idx_surface_v2_reference_contract
ON local_surface_residual_v2_observations(reference_contract_id);

INSERT INTO schema_version(version, applied_at)
SELECT 34, strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
WHERE NOT EXISTS (
    SELECT 1 FROM schema_version WHERE version = 34
);
