-- =====================================================================
-- Christiania — migration 031
-- Historical replay provenance and uniqueness guards.
--
-- SQLite UNIQUE constraints permit multiple NULL values. The v30 outcome
-- table intentionally has either candidate_id or policy_replay_id NULL, so
-- partial indexes are required for source-specific idempotence. Additional
-- triggers make the database verify that replay rows point back to the exact
-- immutable evidence they claim to reconstruct.
-- =====================================================================
PRAGMA foreign_keys = ON;

CREATE UNIQUE INDEX uq_historical_outcome_original_source_v1
ON historical_outcome_recovery_v1(
    replay_run_id,
    source_candidate_id
)
WHERE source_population = 'PROSPECTIVE_ORIGINAL';

CREATE UNIQUE INDEX uq_historical_outcome_replay_source_v1
ON historical_outcome_recovery_v1(
    replay_run_id,
    policy_replay_id
)
WHERE source_population = 'RETROSPECTIVE_POLICY_REPLAY';


CREATE TRIGGER trg_historical_policy_replay_source_guard_v1
BEFORE INSERT ON historical_policy_replay_v1
BEGIN
    SELECT CASE
        WHEN NOT EXISTS (
            SELECT 1
            FROM shadow_admission_decisions AS sad
            WHERE sad.id = NEW.original_admission_decision_id
              AND sad.proposal_id = NEW.proposal_id
              AND sad.fx_observation_id = NEW.original_fx_observation_id
              AND sad.decision = 'BLOCKED'
              AND sad.candidate_id IS NULL
              AND sad.sizing_policy_version =
                  'SIZING_POLICY_V1_FIXED_500_EUR_ONE_UNIT'
              AND sad.reason_code = NEW.original_reason_code
              AND sad.decided_at = NEW.original_decided_at
              AND sad.reason_code IN (
                  'ONE_UNIT_EXCEEDS_EUR_500_BANKROLL',
                  'ACTIVE_PORTFOLIO_EXCEEDS_EUR_500_BANKROLL'
              )
        )
        THEN RAISE(
            ABORT,
            'Historical policy replay must reference an exact immutable wallet-only legacy block.'
        )
    END;

    SELECT CASE
        WHEN NOT EXISTS (
            SELECT 1
            FROM historical_replay_runs_v1 AS run
            WHERE run.id = NEW.replay_run_id
              AND run.source_policy_version =
                  'SIZING_POLICY_V1_FIXED_500_EUR_ONE_UNIT'
              AND run.target_policy_version = NEW.target_risk_policy_version
        )
        THEN RAISE(
            ABORT,
            'Historical policy replay policy lineage does not match its replay run.'
        )
    END;
END;


CREATE TRIGGER trg_historical_replay_mark_source_guard_v1
BEFORE INSERT ON historical_replay_marks_v1
BEGIN
    SELECT CASE
        WHEN NOT EXISTS (
            SELECT 1
            FROM historical_policy_replay_v1 AS hpr
            WHERE hpr.id = NEW.policy_replay_id
              AND hpr.proposal_id = NEW.proposal_id
              AND hpr.counterfactual_decision = 'WOULD_ADMIT'
        )
        THEN RAISE(
            ABORT,
            'Historical replay mark must belong to a would-admit policy replay.'
        )
    END;

    SELECT CASE
        WHEN NEW.snapshot_id IS NOT NULL
         AND NOT EXISTS (
            SELECT 1
            FROM market_snapshots AS ms
            WHERE ms.id = NEW.snapshot_id
              AND ms.research_run_id = NEW.research_run_id
        )
        THEN RAISE(
            ABORT,
            'Historical replay mark snapshot must belong to its research run.'
        )
    END;

    SELECT CASE
        WHEN NOT EXISTS (
            SELECT 1
            FROM historical_policy_replay_v1 AS hpr
            JOIN shadow_structure_proposals AS ssp
              ON ssp.id = hpr.proposal_id
            JOIN research_runs AS rr
              ON rr.id = NEW.research_run_id
            WHERE hpr.id = NEW.policy_replay_id
              AND rr.id > ssp.research_run_id
              AND rr.us_session_date <= ssp.expiration
              AND COALESCE(rr.ended_at, rr.started_at) >= hpr.original_decided_at
        )
        THEN RAISE(
            ABORT,
            'Historical replay mark violates the no-lookahead time window.'
        )
    END;
END;


CREATE TRIGGER trg_historical_outcome_source_guard_v1
BEFORE INSERT ON historical_outcome_recovery_v1
BEGIN
    SELECT CASE
        WHEN NEW.source_population = 'PROSPECTIVE_ORIGINAL'
         AND NOT EXISTS (
            SELECT 1
            FROM shadow_admission_decisions AS sad
            WHERE sad.candidate_id = NEW.source_candidate_id
              AND sad.proposal_id = NEW.proposal_id
              AND sad.decision = 'ADMITTED'
        )
        THEN RAISE(
            ABORT,
            'Original outcome recovery must reference a prospectively admitted legacy candidate.'
        )
    END;

    SELECT CASE
        WHEN NEW.source_population = 'RETROSPECTIVE_POLICY_REPLAY'
         AND NOT EXISTS (
            SELECT 1
            FROM historical_policy_replay_v1 AS hpr
            WHERE hpr.id = NEW.policy_replay_id
              AND hpr.replay_run_id = NEW.replay_run_id
              AND hpr.proposal_id = NEW.proposal_id
              AND hpr.counterfactual_decision = 'WOULD_ADMIT'
        )
        THEN RAISE(
            ABORT,
            'Replay outcome recovery must reference its exact would-admit replay item.'
        )
    END;

    SELECT CASE
        WHEN NEW.snapshot_id IS NOT NULL
         AND NOT EXISTS (
            SELECT 1
            FROM market_snapshots AS ms
            JOIN research_runs AS rr
              ON rr.id = ms.research_run_id
            JOIN shadow_structure_proposals AS ssp
              ON ssp.id = NEW.proposal_id
            WHERE ms.id = NEW.snapshot_id
              AND ms.underlying = ssp.underlying
              AND rr.us_session_date = NEW.expiration
              AND ms.underlying_price IS NOT NULL
        )
        THEN RAISE(
            ABORT,
            'Historical outcome snapshot must be stored underlying evidence from the proposal expiration session.'
        )
    END;
END;


INSERT INTO schema_version(version, applied_at)
SELECT
    31,
    strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
WHERE NOT EXISTS (
    SELECT 1 FROM schema_version WHERE version = 31
);
