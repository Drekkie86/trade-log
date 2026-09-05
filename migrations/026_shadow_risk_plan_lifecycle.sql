PRAGMA foreign_keys = ON;

CREATE TABLE shadow_risk_plans (
    id INTEGER PRIMARY KEY,
    candidate_id INTEGER NOT NULL UNIQUE REFERENCES shadow_candidates(id),
    created_at TEXT NOT NULL,
    plan_version TEXT NOT NULL,
    actor TEXT NOT NULL,
    bankroll_cap_eur_minor INTEGER NOT NULL DEFAULT 50000,
    max_defined_loss_eur_minor INTEGER NOT NULL,
    reserved_risk_eur_minor INTEGER NOT NULL,
    stop_loss_fraction REAL,
    time_stop_at TEXT,
    thesis_invalidation_rule TEXT,
    event_stop_rule TEXT,
    entry_assumption_json TEXT NOT NULL,
    notes TEXT,
    CHECK(length(trim(plan_version)) > 0),
    CHECK(length(trim(actor)) > 0),
    CHECK(bankroll_cap_eur_minor = 50000),
    CHECK(max_defined_loss_eur_minor >= 0 AND max_defined_loss_eur_minor <= bankroll_cap_eur_minor),
    CHECK(reserved_risk_eur_minor > 0 AND reserved_risk_eur_minor <= bankroll_cap_eur_minor),
    CHECK(max_defined_loss_eur_minor <= reserved_risk_eur_minor),
    CHECK(stop_loss_fraction IS NULL OR (stop_loss_fraction > 0 AND stop_loss_fraction <= 1.0)),
    CHECK(json_valid(entry_assumption_json))
);

CREATE TRIGGER trg_shadow_risk_plans_no_update
BEFORE UPDATE ON shadow_risk_plans
BEGIN
    SELECT RAISE(ABORT, 'Shadow risk plans are immutable prospective evidence.');
END;

CREATE TRIGGER trg_shadow_risk_plans_no_delete
BEFORE DELETE ON shadow_risk_plans
BEGIN
    SELECT RAISE(ABORT, 'Shadow risk plans cannot be deleted.');
END;


CREATE TABLE shadow_risk_assessments (
    id INTEGER PRIMARY KEY,
    risk_plan_id INTEGER NOT NULL REFERENCES shadow_risk_plans(id),
    candidate_id INTEGER NOT NULL REFERENCES shadow_candidates(id),
    shadow_mark_id INTEGER REFERENCES shadow_mark_observations(id),
    observed_at TEXT NOT NULL,
    assessment_version TEXT NOT NULL,
    mark_net_pnl_eur_minor INTEGER,
    loss_fraction_reserved REAL,
    price_stop_state TEXT NOT NULL,
    time_stop_state TEXT NOT NULL,
    thesis_stop_state TEXT NOT NULL,
    event_stop_state TEXT NOT NULL,
    overall_state TEXT NOT NULL,
    reason_codes_json TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    CHECK(length(trim(assessment_version)) > 0),
    CHECK(loss_fraction_reserved IS NULL OR loss_fraction_reserved >= 0),
    CHECK(price_stop_state IN ('CLEAR','BREACHED','NOT_CONFIGURED','UNAVAILABLE')),
    CHECK(time_stop_state IN ('CLEAR','BREACHED','NOT_CONFIGURED','UNAVAILABLE')),
    CHECK(thesis_stop_state IN ('CLEAR','BREACHED','NOT_CONFIGURED','UNAVAILABLE')),
    CHECK(event_stop_state IN ('CLEAR','BREACHED','NOT_CONFIGURED','UNAVAILABLE')),
    CHECK(overall_state IN ('CLEAR','REVIEW_REQUIRED','EXIT_TRIGGERED')),
    CHECK(json_valid(reason_codes_json)),
    CHECK(json_valid(evidence_json)),
    UNIQUE(risk_plan_id, shadow_mark_id)
);

CREATE INDEX idx_shadow_risk_assessments_plan_time
ON shadow_risk_assessments(risk_plan_id, observed_at, id);

CREATE TRIGGER trg_shadow_risk_assessment_plan_candidate_guard
BEFORE INSERT ON shadow_risk_assessments
BEGIN
    SELECT CASE
        WHEN NOT EXISTS(
            SELECT 1
            FROM shadow_risk_plans AS p
            WHERE p.id = NEW.risk_plan_id
              AND p.candidate_id = NEW.candidate_id
        )
        THEN RAISE(ABORT, 'Risk assessment candidate must match its frozen risk plan.')
    END;
END;

CREATE TRIGGER trg_shadow_risk_assessment_mark_candidate_guard
BEFORE INSERT ON shadow_risk_assessments
WHEN NEW.shadow_mark_id IS NOT NULL
BEGIN
    SELECT CASE
        WHEN NOT EXISTS(
            SELECT 1
            FROM shadow_mark_observations AS m
            WHERE m.id = NEW.shadow_mark_id
              AND m.candidate_id = NEW.candidate_id
        )
        THEN RAISE(ABORT, 'Risk assessment shadow mark must belong to the same candidate.')
    END;
END;

CREATE TRIGGER trg_shadow_risk_assessments_no_update
BEFORE UPDATE ON shadow_risk_assessments
BEGIN
    SELECT RAISE(ABORT, 'Shadow risk assessments are append-only evidence.');
END;

CREATE TRIGGER trg_shadow_risk_assessments_no_delete
BEFORE DELETE ON shadow_risk_assessments
BEGIN
    SELECT RAISE(ABORT, 'Shadow risk assessments cannot be deleted.');
END;


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
    p.created_at AS risk_plan_created_at,
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
LEFT JOIN ranked AS r
  ON r.risk_plan_id = p.id
 AND r.rn = 1;

INSERT INTO schema_version(version, applied_at)
SELECT 26, strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
WHERE NOT EXISTS(
    SELECT 1 FROM schema_version WHERE version = 26
);
