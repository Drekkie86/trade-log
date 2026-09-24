-- =====================================================================
-- Christiania — migration 034
--
-- Storage V2C parent-delete FK support.
--
-- SQLite verifies child foreign keys while deleting parent rows. Parent
-- deletes can become effectively quadratic when the child FK column is not
-- the leading column of an index. Storage V2C deletes old rows from
-- listing_reference_contracts and option_quotes, so every child FK into those
-- parents must have a leading support index.
--
-- This migration adds the four support indexes proven missing by the
-- complete migration-history audit and an immutable low-volume prune commit
-- ledger. The ledger closes the durability gap between the SQLite commit and
-- the external JSON receipt: the full receipt payload commits atomically with
-- the delete transaction and can recreate a missing external receipt.
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

CREATE TABLE research_archive_prune_commits_v1 (
    session_date                   TEXT PRIMARY KEY,
    committed_at                   TEXT NOT NULL,
    state                          TEXT NOT NULL
                                   CHECK (
                                       state =
                                       'REFERENCE_AWARE_HOT_PRUNE_COMMITTED'
                                   ),
    schema_version                 INTEGER NOT NULL
                                   CHECK (schema_version >= 34),
    archive_manifest_sha256        TEXT NOT NULL
                                   CHECK (
                                       length(archive_manifest_sha256) = 64
                                   ),
    remote_proof_sha256            TEXT NOT NULL
                                   CHECK (
                                       length(remote_proof_sha256) = 64
                                   ),
    historical_analysis_version    INTEGER NOT NULL
                                   CHECK (
                                       historical_analysis_version >= 1
                                   ),
    hot_analysis_sha256            TEXT NOT NULL
                                   CHECK (
                                       length(hot_analysis_sha256) = 64
                                   ),
    archive_analysis_sha256        TEXT NOT NULL
                                   CHECK (
                                       length(archive_analysis_sha256) = 64
                                   ),
    receipt_json                   TEXT NOT NULL
                                   CHECK (json_valid(receipt_json)),
    receipt_sha256                 TEXT NOT NULL
                                   CHECK (
                                       length(receipt_sha256) = 64
                                   )
);

CREATE TRIGGER trg_research_archive_prune_commit_no_update_v1
BEFORE UPDATE ON research_archive_prune_commits_v1
BEGIN
    SELECT RAISE(
        ABORT,
        'Research archive prune commit evidence is immutable.'
    );
END;

CREATE TRIGGER trg_research_archive_prune_commit_no_delete_v1
BEFORE DELETE ON research_archive_prune_commits_v1
BEGIN
    SELECT RAISE(
        ABORT,
        'Research archive prune commit evidence cannot be deleted.'
    );
END;


INSERT INTO schema_version(version, applied_at)
SELECT
    34,
    strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
WHERE NOT EXISTS (
    SELECT 1
    FROM schema_version
    WHERE version = 34
);
