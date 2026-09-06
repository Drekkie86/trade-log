-- =====================================================================
-- Christiania — migration 027
-- Pre-RC integrity hardening.
--
-- 1. Make prospective risk-plan origin DB-recorded rather than trusting a
--    caller-supplied effective timestamp.
-- 2. Refuse any NEW risk plan once any shadow mark already exists for that
--    candidate, irrespective of claimed timestamps.
-- 3. Persist predeclared risk-trigger exits as a separate measurement
--    population; never silently mix them with raw/terminal shadow marks.
-- =====================================================================

PRAGMA foreign_keys = ON;

CREATE TABLE shadow_risk_plan_recordings (
    risk_plan_id            INTEGER PRIMARY KEY
                            REFERENCES shadow_risk_plans(id),
    candidate_id            INTEGER NOT NULL UNIQUE
                            REFERENCES shadow_candidates(id),
    recorded_at             TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    prospectivity_state     TEXT NOT NULL,
    CHECK (
        prospectivity_state IN (
            'DB_RECORDED_PROSPECTIVE',
            'LEGACY_UNVERIFIED'
        )
    )
);

CREATE TRIGGER trg_shadow_risk_plan_recording_candidate_guard
BEFORE INSERT ON shadow_risk_plan_recordings
BEGIN
    SELECT CASE
        WHEN NOT EXISTS (
            SELECT 1
            FROM shadow_risk_plans AS p
            WHERE p.id = NEW.risk_plan_id
              AND p.candidate_id = NEW.candidate_id
        )
        THEN RAISE(
            ABORT,
            'Risk-plan recording candidate must match the risk plan.'
        )
    END;
END;

CREATE TRIGGER trg_shadow_risk_plan_recordings_no_update
BEFORE UPDATE ON shadow_risk_plan_recordings
BEGIN
    SELECT RAISE(ABORT, 'Risk-plan recording evidence is immutable.');
END;

CREATE TRIGGER trg_shadow_risk_plan_recordings_no_delete
BEFORE DELETE ON shadow_risk_plan_recordings
BEGIN
    SELECT RAISE(ABORT, 'Risk-plan recording evidence cannot be deleted.');
END;

-- Existing v26 plans cannot retroactively prove their actual insertion time.
INSERT INTO shadow_risk_plan_recordings(
    risk_plan_id,
    candidate_id,
    prospectivity_state
)
SELECT
    id,
    candidate_id,
    'LEGACY_UNVERIFIED'
FROM shadow_risk_plans;

CREATE TRIGGER trg_shadow_risk_plan_refuse_prior_marks
BEFORE INSERT ON shadow_risk_plans
BEGIN
    SELECT CASE
        WHEN EXISTS (
            SELECT 1
            FROM shadow_mark_observations AS m
            WHERE m.candidate_id = NEW.candidate_id
        )
        THEN RAISE(
            ABORT,
            'Prospective risk plan refused: candidate already has shadow marks.'
        )
    END;
END;

CREATE TRIGGER trg_shadow_risk_plan_record_origin
AFTER INSERT ON shadow_risk_plans
BEGIN
    INSERT INTO shadow_risk_plan_recordings(
        risk_plan_id,
        candidate_id,
        prospectivity_state
    )
    VALUES(
        NEW.id,
        NEW.candidate_id,
        'DB_RECORDED_PROSPECTIVE'
    );
END;

CREATE TABLE shadow_risk_exit_outcomes (
    id                          INTEGER PRIMARY KEY,
    risk_plan_id                INTEGER NOT NULL UNIQUE
                                REFERENCES shadow_risk_plans(id),
    candidate_id                INTEGER NOT NULL
                                REFERENCES shadow_candidates(id),
    risk_assessment_id          INTEGER NOT NULL UNIQUE
                                REFERENCES shadow_risk_assessments(id),
    shadow_mark_id              INTEGER NOT NULL UNIQUE
                                REFERENCES shadow_mark_observations(id),
    observed_at                 TEXT NOT NULL,
    estimated_net_pnl_eur_minor INTEGER,
    measurement_role            TEXT NOT NULL
                                DEFAULT 'PREDECLARED_RISK_EXIT_OUTCOME',
    evidence_eligible           INTEGER NOT NULL,
    source_measurement_role     TEXT NOT NULL,
    source_outcome_eligible     INTEGER NOT NULL,
    prospectivity_state         TEXT NOT NULL,
    CHECK (measurement_role = 'PREDECLARED_RISK_EXIT_OUTCOME'),
    CHECK (evidence_eligible IN (0,1)),
    CHECK (source_outcome_eligible IN (0,1)),
    CHECK (
        prospectivity_state IN (
            'DB_RECORDED_PROSPECTIVE',
            'LEGACY_UNVERIFIED'
        )
    )
);

CREATE TRIGGER trg_shadow_risk_exit_outcomes_no_update
BEFORE UPDATE ON shadow_risk_exit_outcomes
BEGIN
    SELECT RAISE(ABORT, 'Shadow risk-exit outcomes are immutable evidence.');
END;

CREATE TRIGGER trg_shadow_risk_exit_outcomes_no_delete
BEFORE DELETE ON shadow_risk_exit_outcomes
BEGIN
    SELECT RAISE(ABORT, 'Shadow risk-exit outcomes cannot be deleted.');
END;

CREATE TRIGGER trg_shadow_risk_exit_outcome_capture
AFTER INSERT ON shadow_risk_assessments
WHEN NEW.overall_state = 'EXIT_TRIGGERED'
 AND NEW.shadow_mark_id IS NOT NULL
BEGIN
    INSERT OR IGNORE INTO shadow_risk_exit_outcomes(
        risk_plan_id,
        candidate_id,
        risk_assessment_id,
        shadow_mark_id,
        observed_at,
        estimated_net_pnl_eur_minor,
        evidence_eligible,
        source_measurement_role,
        source_outcome_eligible,
        prospectivity_state
    )
    SELECT
        NEW.risk_plan_id,
        NEW.candidate_id,
        NEW.id,
        NEW.shadow_mark_id,
        NEW.observed_at,
        m.estimated_net_pnl_eur_minor,
        CASE
            WHEN m.outcome_eligible = 1
             AND r.prospectivity_state = 'DB_RECORDED_PROSPECTIVE'
            THEN 1 ELSE 0
        END,
        m.measurement_role,
        m.outcome_eligible,
        r.prospectivity_state
    FROM shadow_mark_observations AS m
    JOIN shadow_risk_plan_recordings AS r
      ON r.risk_plan_id = NEW.risk_plan_id
     AND r.candidate_id = NEW.candidate_id
    WHERE m.id = NEW.shadow_mark_id
      AND m.candidate_id = NEW.candidate_id;
END;

DROP VIEW v_shadow_risk_current;

CREATE VIEW v_shadow_risk_current AS
WITH ranked AS (
    SELECT
        a.*,
        ROW_NUMBER() OVER(
            PARTITION BY risk_plan_id
            ORDER BY observed_at DESC, id DESC
        ) AS rn
    FROM shadow_risk_assessments AS a
)
SELECT
    p.id AS risk_plan_id,
    p.candidate_id,
    p.created_at AS risk_plan_effective_at,
    rec.recorded_at AS risk_plan_recorded_at,
    rec.prospectivity_state,
    p.plan_version,
    p.bankroll_cap_eur_minor,
    p.max_defined_loss_eur_minor,
    p.reserved_risk_eur_minor,
    p.stop_loss_fraction,
    p.time_stop_at,
    p.thesis_invalidation_rule,
    p.event_stop_rule,
    r.id AS latest_assessment_id,
    r.observed_at AS latest_assessment_at,
    r.mark_net_pnl_eur_minor,
    r.loss_fraction_reserved,
    r.price_stop_state,
    r.time_stop_state,
    r.thesis_stop_state,
    r.event_stop_state,
    r.overall_state
FROM shadow_risk_plans AS p
JOIN shadow_risk_plan_recordings AS rec
  ON rec.risk_plan_id = p.id
LEFT JOIN ranked AS r
  ON r.risk_plan_id = p.id
 AND r.rn = 1;

CREATE VIEW v_shadow_outcome_populations_v1 AS
SELECT
    smo.candidate_id,
    smo.observed_at,
    smo.estimated_net_pnl_eur_minor,
    smo.measurement_role,
    smo.outcome_eligible AS evidence_eligible,
    'SHADOW_MARK' AS source_family,
    smo.id AS source_id
FROM shadow_mark_observations AS smo
UNION ALL
SELECT
    reo.candidate_id,
    reo.observed_at,
    reo.estimated_net_pnl_eur_minor,
    reo.measurement_role,
    reo.evidence_eligible,
    'PREDECLARED_RISK_EXIT' AS source_family,
    reo.id AS source_id
FROM shadow_risk_exit_outcomes AS reo;

INSERT INTO schema_version(version, applied_at)
SELECT
    27,
    strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
WHERE NOT EXISTS (
    SELECT 1 FROM schema_version WHERE version = 27
);
