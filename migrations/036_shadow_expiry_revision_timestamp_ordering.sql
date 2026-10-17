-- Append-only correction for expiry-outcome revision chronology.
-- Never modify the already published migration 035 in-place.
-- UTC timestamps may be represented with Z, +00:00 or other explicit offsets.
-- Lexicographic text comparisons do not preserve chronological order across
-- these representations. julianday() compares actual instants.
DROP TRIGGER IF EXISTS trg_shadow_expiry_outcomes_revision_v1;

CREATE TRIGGER trg_shadow_expiry_outcomes_revision_v1
BEFORE INSERT ON shadow_expiry_outcomes_v1
WHEN (
    (NEW.revision = 1 AND EXISTS (
        SELECT 1 FROM shadow_expiry_outcomes_v1
        WHERE candidate_id = NEW.candidate_id
    ))
    OR
    (NEW.revision > 1 AND NOT EXISTS (
        SELECT 1 FROM shadow_expiry_outcomes_v1 AS prior
        WHERE prior.id = NEW.supersedes_outcome_id
          AND prior.candidate_id = NEW.candidate_id
          AND prior.revision = NEW.revision - 1
          AND prior.revision = (
              SELECT MAX(revision) FROM shadow_expiry_outcomes_v1
              WHERE candidate_id = NEW.candidate_id
          )
          AND (
              (NEW.outcome_state = 'RESOLVED'
               AND (prior.outcome_state = 'UNRESOLVED'
                    OR (prior.outcome_state = 'RESOLVED'
                        AND prior.snapshot_id <> NEW.snapshot_id
                        AND julianday(NEW.snapshot_captured_at)
                            > julianday(prior.snapshot_captured_at))))
              OR
              (NEW.outcome_state = 'UNRESOLVED'
               AND prior.outcome_state = 'UNRESOLVED'
               AND NEW.reason_code <> prior.reason_code)
          )
    ))
)
BEGIN
    SELECT RAISE(ABORT, 'Invalid expiry outcome evidence supersession.');
END;

INSERT INTO schema_version(version, applied_at)
SELECT 36, strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
WHERE NOT EXISTS (SELECT 1 FROM schema_version WHERE version = 36);
