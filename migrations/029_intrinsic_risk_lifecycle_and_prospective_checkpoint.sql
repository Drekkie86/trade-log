-- =====================================================================
-- Christiania — migration 029
--
-- 1. Decouple research admission from any external account/bankroll amount.
-- 2. Add an intrinsic-risk risk-plan population with no wallet ceiling.
-- 3. Persist append-only prospective hypothesis checkpoint evaluations.
--
-- Historical EUR-500 evidence remains immutable in the legacy tables. New
-- research evidence is written to the V1 intrinsic-risk tables below.
-- =====================================================================
PRAGMA foreign_keys = ON;

CREATE TABLE shadow_intrinsic_admission_decisions_v1 (
    id                           INTEGER PRIMARY KEY,
    proposal_id                  INTEGER NOT NULL
                                 REFERENCES shadow_structure_proposals(id),
    fx_observation_id            INTEGER NOT NULL
                                 REFERENCES fx_observations(id),
    candidate_id                 INTEGER
                                 REFERENCES shadow_candidates(id),
    risk_policy_version          TEXT NOT NULL,
    cost_model_version           TEXT NOT NULL,
    cost_provenance              TEXT NOT NULL,
    proposal_max_loss_usd_minor  INTEGER NOT NULL,
    estimated_cost_usd_minor     INTEGER NOT NULL,
    intrinsic_risk_usd_minor     INTEGER NOT NULL,
    converted_max_loss_eur_minor INTEGER NOT NULL,
    estimated_cost_eur_minor     INTEGER NOT NULL,
    intrinsic_risk_eur_minor     INTEGER NOT NULL,
    decision                     TEXT NOT NULL,
    reason_code                  TEXT NOT NULL,
    decided_at                   TEXT NOT NULL,
    evidence_json                TEXT NOT NULL,
    UNIQUE(proposal_id, risk_policy_version, cost_model_version),
    CHECK(length(trim(risk_policy_version)) > 0),
    CHECK(proposal_max_loss_usd_minor > 0),
    CHECK(estimated_cost_usd_minor >= 0),
    CHECK(intrinsic_risk_usd_minor >= proposal_max_loss_usd_minor),
    CHECK(converted_max_loss_eur_minor > 0),
    CHECK(estimated_cost_eur_minor >= 0),
    CHECK(intrinsic_risk_eur_minor >= converted_max_loss_eur_minor),
    CHECK(decision IN ('ADMITTED','BLOCKED')),
    CHECK(
        (decision = 'ADMITTED' AND candidate_id IS NOT NULL)
        OR (decision = 'BLOCKED' AND candidate_id IS NULL)
    ),
    CHECK(json_valid(evidence_json))
);

CREATE INDEX idx_shadow_intrinsic_admission_proposal_v1
ON shadow_intrinsic_admission_decisions_v1(proposal_id);

CREATE INDEX idx_shadow_intrinsic_admission_candidate_v1
ON shadow_intrinsic_admission_decisions_v1(candidate_id);

CREATE TRIGGER trg_shadow_intrinsic_admission_no_update_v1
BEFORE UPDATE ON shadow_intrinsic_admission_decisions_v1
BEGIN
    SELECT RAISE(ABORT, 'Intrinsic-risk shadow admission evidence is immutable.');
END;

CREATE TRIGGER trg_shadow_intrinsic_admission_no_delete_v1
BEFORE DELETE ON shadow_intrinsic_admission_decisions_v1
BEGIN
    SELECT RAISE(ABORT, 'Intrinsic-risk shadow admission evidence cannot be deleted.');
END;

-- One normalized read surface keeps historical capped decisions auditable
-- while making new intrinsic-risk decisions visible to outcome tracking and
-- the dashboard. bankroll_cap_eur_minor is NULL for all new decisions.
CREATE VIEW v_shadow_admission_decisions_all AS
SELECT
    sad.id AS decision_id,
    'LEGACY_BANKROLL_POLICY' AS decision_source,
    sad.proposal_id,
    sad.fx_observation_id,
    sad.candidate_id,
    sad.sizing_policy_version AS risk_policy_version,
    sad.sizing_policy_version,
    sad.cost_model_version,
    sad.cost_provenance,
    sad.proposal_max_loss_usd_minor,
    sad.estimated_cost_usd_minor,
    sad.reserved_risk_usd_minor AS intrinsic_risk_usd_minor,
    sad.reserved_risk_usd_minor,
    sad.converted_max_loss_eur_minor,
    sad.estimated_cost_eur_minor,
    sad.reserved_risk_eur_minor AS intrinsic_risk_eur_minor,
    sad.reserved_risk_eur_minor,
    sad.bankroll_cap_eur_minor,
    sad.decision,
    sad.reason_code,
    sad.decided_at,
    sad.evidence_json
FROM shadow_admission_decisions AS sad
UNION ALL
SELECT
    iad.id AS decision_id,
    'INTRINSIC_RISK_POLICY_V1' AS decision_source,
    iad.proposal_id,
    iad.fx_observation_id,
    iad.candidate_id,
    iad.risk_policy_version,
    iad.risk_policy_version AS sizing_policy_version,
    iad.cost_model_version,
    iad.cost_provenance,
    iad.proposal_max_loss_usd_minor,
    iad.estimated_cost_usd_minor,
    iad.intrinsic_risk_usd_minor,
    iad.intrinsic_risk_usd_minor AS reserved_risk_usd_minor,
    iad.converted_max_loss_eur_minor,
    iad.estimated_cost_eur_minor,
    iad.intrinsic_risk_eur_minor,
    iad.intrinsic_risk_eur_minor AS reserved_risk_eur_minor,
    NULL AS bankroll_cap_eur_minor,
    iad.decision,
    iad.reason_code,
    iad.decided_at,
    iad.evidence_json
FROM shadow_intrinsic_admission_decisions_v1 AS iad;


-- =====================================================================
-- Intrinsic risk plans. The risk basis belongs to the trade/research object;
-- no account balance, wallet balance, or bankroll ceiling is stored here.
-- =====================================================================
CREATE TABLE shadow_intrinsic_risk_plans_v1 (
    id                         INTEGER PRIMARY KEY,
    candidate_id               INTEGER NOT NULL UNIQUE
                               REFERENCES shadow_candidates(id),
    created_at                 TEXT NOT NULL,
    plan_version               TEXT NOT NULL,
    actor                      TEXT NOT NULL,
    max_defined_loss_eur_minor INTEGER NOT NULL,
    risk_basis_eur_minor       INTEGER NOT NULL,
    stop_loss_fraction         REAL,
    time_stop_at               TEXT,
    thesis_invalidation_rule   TEXT,
    event_stop_rule            TEXT,
    entry_assumption_json      TEXT NOT NULL,
    notes                      TEXT,
    CHECK(length(trim(plan_version)) > 0),
    CHECK(length(trim(actor)) > 0),
    CHECK(max_defined_loss_eur_minor >= 0),
    CHECK(risk_basis_eur_minor > 0),
    CHECK(max_defined_loss_eur_minor <= risk_basis_eur_minor),
    CHECK(stop_loss_fraction IS NULL OR (stop_loss_fraction > 0 AND stop_loss_fraction <= 1.0)),
    CHECK(json_valid(entry_assumption_json))
);

CREATE TRIGGER trg_shadow_intrinsic_risk_plans_no_update_v1
BEFORE UPDATE ON shadow_intrinsic_risk_plans_v1
BEGIN
    SELECT RAISE(ABORT, 'Intrinsic shadow risk plans are immutable prospective evidence.');
END;

CREATE TRIGGER trg_shadow_intrinsic_risk_plans_no_delete_v1
BEFORE DELETE ON shadow_intrinsic_risk_plans_v1
BEGIN
    SELECT RAISE(ABORT, 'Intrinsic shadow risk plans cannot be deleted.');
END;

CREATE TRIGGER trg_shadow_intrinsic_risk_plan_refuse_prior_marks_v1
BEFORE INSERT ON shadow_intrinsic_risk_plans_v1
BEGIN
    SELECT CASE
        WHEN EXISTS (
            SELECT 1
            FROM shadow_mark_observations AS m
            WHERE m.candidate_id = NEW.candidate_id
        )
        THEN RAISE(ABORT, 'Prospective risk plan refused: candidate already has shadow marks.')
    END;
END;

CREATE TABLE shadow_intrinsic_risk_plan_recordings_v1 (
    risk_plan_id        INTEGER PRIMARY KEY
                        REFERENCES shadow_intrinsic_risk_plans_v1(id),
    candidate_id        INTEGER NOT NULL UNIQUE
                        REFERENCES shadow_candidates(id),
    recorded_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    prospectivity_state TEXT NOT NULL CHECK(prospectivity_state='DB_RECORDED_PROSPECTIVE')
);

CREATE TRIGGER trg_shadow_intrinsic_risk_plan_recording_candidate_guard_v1
BEFORE INSERT ON shadow_intrinsic_risk_plan_recordings_v1
BEGIN
    SELECT CASE
        WHEN NOT EXISTS (
            SELECT 1
            FROM shadow_intrinsic_risk_plans_v1 AS p
            WHERE p.id = NEW.risk_plan_id
              AND p.candidate_id = NEW.candidate_id
        )
        THEN RAISE(ABORT, 'Intrinsic risk-plan recording candidate must match the risk plan.')
    END;
END;

CREATE TRIGGER trg_shadow_intrinsic_risk_plan_recordings_no_update_v1
BEFORE UPDATE ON shadow_intrinsic_risk_plan_recordings_v1
BEGIN
    SELECT RAISE(ABORT, 'Intrinsic risk-plan recording evidence is immutable.');
END;

CREATE TRIGGER trg_shadow_intrinsic_risk_plan_recordings_no_delete_v1
BEFORE DELETE ON shadow_intrinsic_risk_plan_recordings_v1
BEGIN
    SELECT RAISE(ABORT, 'Intrinsic risk-plan recording evidence cannot be deleted.');
END;

CREATE TRIGGER trg_shadow_intrinsic_risk_plan_record_origin_v1
AFTER INSERT ON shadow_intrinsic_risk_plans_v1
BEGIN
    INSERT INTO shadow_intrinsic_risk_plan_recordings_v1(
        risk_plan_id, candidate_id, prospectivity_state
    ) VALUES(NEW.id, NEW.candidate_id, 'DB_RECORDED_PROSPECTIVE');
END;

CREATE TABLE shadow_intrinsic_risk_assessments_v1 (
    id                         INTEGER PRIMARY KEY,
    risk_plan_id               INTEGER NOT NULL
                               REFERENCES shadow_intrinsic_risk_plans_v1(id),
    candidate_id               INTEGER NOT NULL REFERENCES shadow_candidates(id),
    shadow_mark_id             INTEGER REFERENCES shadow_mark_observations(id),
    observed_at                TEXT NOT NULL,
    assessment_version         TEXT NOT NULL,
    mark_net_pnl_eur_minor     INTEGER,
    loss_fraction_risk_basis   REAL,
    price_stop_state           TEXT NOT NULL,
    time_stop_state            TEXT NOT NULL,
    thesis_stop_state          TEXT NOT NULL,
    event_stop_state           TEXT NOT NULL,
    overall_state              TEXT NOT NULL,
    reason_codes_json          TEXT NOT NULL,
    evidence_json              TEXT NOT NULL,
    CHECK(length(trim(assessment_version)) > 0),
    CHECK(loss_fraction_risk_basis IS NULL OR loss_fraction_risk_basis >= 0),
    CHECK(price_stop_state IN ('CLEAR','BREACHED','NOT_CONFIGURED','UNAVAILABLE')),
    CHECK(time_stop_state IN ('CLEAR','BREACHED','NOT_CONFIGURED','UNAVAILABLE')),
    CHECK(thesis_stop_state IN ('CLEAR','BREACHED','NOT_CONFIGURED','UNAVAILABLE')),
    CHECK(event_stop_state IN ('CLEAR','BREACHED','NOT_CONFIGURED','UNAVAILABLE')),
    CHECK(overall_state IN ('CLEAR','REVIEW_REQUIRED','EXIT_TRIGGERED')),
    CHECK(json_valid(reason_codes_json)),
    CHECK(json_valid(evidence_json)),
    UNIQUE(risk_plan_id, shadow_mark_id)
);

CREATE INDEX idx_shadow_intrinsic_risk_assessments_plan_time_v1
ON shadow_intrinsic_risk_assessments_v1(risk_plan_id, observed_at, id);

CREATE TRIGGER trg_shadow_intrinsic_risk_assessment_plan_candidate_guard_v1
BEFORE INSERT ON shadow_intrinsic_risk_assessments_v1
BEGIN
    SELECT CASE
        WHEN NOT EXISTS(
            SELECT 1 FROM shadow_intrinsic_risk_plans_v1 AS p
            WHERE p.id = NEW.risk_plan_id AND p.candidate_id = NEW.candidate_id
        )
        THEN RAISE(ABORT, 'Intrinsic risk assessment candidate must match its frozen risk plan.')
    END;
END;

CREATE TRIGGER trg_shadow_intrinsic_risk_assessment_mark_candidate_guard_v1
BEFORE INSERT ON shadow_intrinsic_risk_assessments_v1
WHEN NEW.shadow_mark_id IS NOT NULL
BEGIN
    SELECT CASE
        WHEN NOT EXISTS(
            SELECT 1 FROM shadow_mark_observations AS m
            WHERE m.id = NEW.shadow_mark_id AND m.candidate_id = NEW.candidate_id
        )
        THEN RAISE(ABORT, 'Intrinsic risk assessment mark must belong to the same candidate.')
    END;
END;

CREATE TRIGGER trg_shadow_intrinsic_risk_assessments_no_update_v1
BEFORE UPDATE ON shadow_intrinsic_risk_assessments_v1
BEGIN
    SELECT RAISE(ABORT, 'Intrinsic shadow risk assessments are append-only evidence.');
END;

CREATE TRIGGER trg_shadow_intrinsic_risk_assessments_no_delete_v1
BEFORE DELETE ON shadow_intrinsic_risk_assessments_v1
BEGIN
    SELECT RAISE(ABORT, 'Intrinsic shadow risk assessments cannot be deleted.');
END;

CREATE TABLE shadow_intrinsic_risk_exit_outcomes_v1 (
    id                           INTEGER PRIMARY KEY,
    risk_plan_id                 INTEGER NOT NULL UNIQUE
                                 REFERENCES shadow_intrinsic_risk_plans_v1(id),
    candidate_id                 INTEGER NOT NULL REFERENCES shadow_candidates(id),
    risk_assessment_id           INTEGER NOT NULL UNIQUE
                                 REFERENCES shadow_intrinsic_risk_assessments_v1(id),
    shadow_mark_id               INTEGER NOT NULL UNIQUE REFERENCES shadow_mark_observations(id),
    observed_at                  TEXT NOT NULL,
    estimated_net_pnl_eur_minor  INTEGER,
    measurement_role             TEXT NOT NULL DEFAULT 'PREDECLARED_RISK_EXIT_OUTCOME',
    evidence_eligible            INTEGER NOT NULL,
    source_measurement_role      TEXT NOT NULL,
    source_outcome_eligible      INTEGER NOT NULL,
    prospectivity_state          TEXT NOT NULL,
    CHECK(measurement_role='PREDECLARED_RISK_EXIT_OUTCOME'),
    CHECK(evidence_eligible IN (0,1)),
    CHECK(source_outcome_eligible IN (0,1)),
    CHECK(prospectivity_state='DB_RECORDED_PROSPECTIVE')
);

CREATE TRIGGER trg_shadow_intrinsic_risk_exit_outcomes_no_update_v1
BEFORE UPDATE ON shadow_intrinsic_risk_exit_outcomes_v1
BEGIN
    SELECT RAISE(ABORT, 'Intrinsic shadow risk-exit outcomes are immutable evidence.');
END;

CREATE TRIGGER trg_shadow_intrinsic_risk_exit_outcomes_no_delete_v1
BEFORE DELETE ON shadow_intrinsic_risk_exit_outcomes_v1
BEGIN
    SELECT RAISE(ABORT, 'Intrinsic shadow risk-exit outcomes cannot be deleted.');
END;

CREATE TRIGGER trg_shadow_intrinsic_risk_exit_outcome_capture_v1
AFTER INSERT ON shadow_intrinsic_risk_assessments_v1
WHEN NEW.overall_state='EXIT_TRIGGERED' AND NEW.shadow_mark_id IS NOT NULL
BEGIN
    INSERT OR IGNORE INTO shadow_intrinsic_risk_exit_outcomes_v1(
        risk_plan_id, candidate_id, risk_assessment_id, shadow_mark_id,
        observed_at, estimated_net_pnl_eur_minor, evidence_eligible,
        source_measurement_role, source_outcome_eligible, prospectivity_state
    )
    SELECT
        NEW.risk_plan_id, NEW.candidate_id, NEW.id, NEW.shadow_mark_id,
        NEW.observed_at, m.estimated_net_pnl_eur_minor,
        CASE WHEN m.outcome_eligible=1 THEN 1 ELSE 0 END,
        m.measurement_role, m.outcome_eligible, rec.prospectivity_state
    FROM shadow_mark_observations AS m
    JOIN shadow_intrinsic_risk_plan_recordings_v1 AS rec
      ON rec.risk_plan_id=NEW.risk_plan_id AND rec.candidate_id=NEW.candidate_id
    WHERE m.id=NEW.shadow_mark_id AND m.candidate_id=NEW.candidate_id;
END;

CREATE VIEW v_shadow_intrinsic_risk_current_v1 AS
WITH ranked AS (
    SELECT a.*,
           ROW_NUMBER() OVER(PARTITION BY risk_plan_id ORDER BY observed_at DESC,id DESC) AS rn
    FROM shadow_intrinsic_risk_assessments_v1 AS a
)
SELECT
    p.id AS risk_plan_id,
    p.candidate_id,
    p.created_at AS risk_plan_effective_at,
    rec.recorded_at AS risk_plan_recorded_at,
    rec.prospectivity_state,
    p.plan_version,
    p.max_defined_loss_eur_minor,
    p.risk_basis_eur_minor,
    p.stop_loss_fraction,
    p.time_stop_at,
    p.thesis_invalidation_rule,
    p.event_stop_rule,
    r.id AS latest_assessment_id,
    r.observed_at AS latest_assessment_at,
    r.mark_net_pnl_eur_minor,
    r.loss_fraction_risk_basis,
    r.price_stop_state,
    r.time_stop_state,
    r.thesis_stop_state,
    r.event_stop_state,
    r.overall_state
FROM shadow_intrinsic_risk_plans_v1 AS p
JOIN shadow_intrinsic_risk_plan_recordings_v1 AS rec ON rec.risk_plan_id=p.id
LEFT JOIN ranked AS r ON r.risk_plan_id=p.id AND r.rn=1;

CREATE VIEW v_shadow_risk_current_v2 AS
SELECT
    'LEGACY_BANKROLL_POLICY' AS risk_plan_source,
    risk_plan_id,
    candidate_id,
    risk_plan_effective_at,
    risk_plan_recorded_at,
    prospectivity_state,
    plan_version,
    bankroll_cap_eur_minor AS legacy_bankroll_cap_eur_minor,
    max_defined_loss_eur_minor,
    reserved_risk_eur_minor AS risk_basis_eur_minor,
    stop_loss_fraction,
    time_stop_at,
    thesis_invalidation_rule,
    event_stop_rule,
    latest_assessment_id,
    latest_assessment_at,
    mark_net_pnl_eur_minor,
    loss_fraction_reserved AS loss_fraction_risk_basis,
    price_stop_state,
    time_stop_state,
    thesis_stop_state,
    event_stop_state,
    overall_state
FROM v_shadow_risk_current
UNION ALL
SELECT
    'INTRINSIC_RISK_POLICY_V1',
    risk_plan_id,
    candidate_id,
    risk_plan_effective_at,
    risk_plan_recorded_at,
    prospectivity_state,
    plan_version,
    NULL,
    max_defined_loss_eur_minor,
    risk_basis_eur_minor,
    stop_loss_fraction,
    time_stop_at,
    thesis_invalidation_rule,
    event_stop_rule,
    latest_assessment_id,
    latest_assessment_at,
    mark_net_pnl_eur_minor,
    loss_fraction_risk_basis,
    price_stop_state,
    time_stop_state,
    thesis_stop_state,
    event_stop_state,
    overall_state
FROM v_shadow_intrinsic_risk_current_v1;


-- =====================================================================
-- Prospective research checkpoint evidence.
-- Frozen hypotheses remain immutable definitions; evaluations are append-only.
-- =====================================================================
CREATE TABLE prospective_research_hypothesis_evaluations_v1 (
    id                         INTEGER PRIMARY KEY,
    freeze_run_id              INTEGER NOT NULL
                               REFERENCES prospective_research_freeze_v1_runs(id),
    hypothesis_id              INTEGER NOT NULL
                               REFERENCES prospective_research_hypotheses_v1(id),
    hypothesis_key             TEXT NOT NULL,
    evaluation_version         TEXT NOT NULL,
    evaluated_at               TEXT NOT NULL,
    evidence_start_session_date TEXT,
    evidence_end_session_date  TEXT,
    independent_date_count     INTEGER NOT NULL,
    observation_count          INTEGER NOT NULL,
    evaluation_state           TEXT NOT NULL,
    metrics_json               TEXT NOT NULL,
    p_values_enabled           INTEGER NOT NULL DEFAULT 0 CHECK(p_values_enabled=0),
    fdr_enabled                INTEGER NOT NULL DEFAULT 0 CHECK(fdr_enabled=0),
    decision_enabled           INTEGER NOT NULL DEFAULT 0 CHECK(decision_enabled=0),
    CHECK(independent_date_count >= 0),
    CHECK(observation_count >= 0),
    CHECK(evaluation_state IN(
        'INSUFFICIENT_INDEPENDENT_DATES',
        'DESCRIPTIVE_CHECKPOINT_READY',
        'NOT_EVALUABLE'
    )),
    CHECK(json_valid(metrics_json)),
    UNIQUE(freeze_run_id,hypothesis_id,evaluation_version,evidence_end_session_date)
);

CREATE INDEX idx_prospective_hypothesis_eval_latest_v1
ON prospective_research_hypothesis_evaluations_v1(hypothesis_id,id);

CREATE TRIGGER trg_prospective_hypothesis_eval_no_update_v1
BEFORE UPDATE ON prospective_research_hypothesis_evaluations_v1
BEGIN
    SELECT RAISE(ABORT, 'Prospective hypothesis evaluations are immutable evidence.');
END;

CREATE TRIGGER trg_prospective_hypothesis_eval_no_delete_v1
BEFORE DELETE ON prospective_research_hypothesis_evaluations_v1
BEGIN
    SELECT RAISE(ABORT, 'Prospective hypothesis evaluations cannot be deleted.');
END;

CREATE VIEW v_prospective_research_hypothesis_latest_v1 AS
WITH ranked AS (
    SELECT e.*,
           ROW_NUMBER() OVER(PARTITION BY hypothesis_id ORDER BY id DESC) AS rn
    FROM prospective_research_hypothesis_evaluations_v1 AS e
)
SELECT * FROM ranked WHERE rn=1;

INSERT INTO schema_version(version,applied_at)
SELECT 29,strftime('%Y-%m-%dT%H:%M:%SZ','now')
WHERE NOT EXISTS(SELECT 1 FROM schema_version WHERE version=29);
