-- =====================================================================
-- Christiania — migration 033
--
-- Counterfactual Rejection Audit V1.
--
-- Freeze a fixed historical cohort before outcome labels become available:
--   * prospectively admitted legacy structures;
--   * prospectively wallet-blocked legacy structures that the immutable
--     account-independent replay classifies WOULD_ADMIT.
--
-- The old EUR-500 wallet gate is provenance only. It is explicitly forbidden
-- as a predictive feature. Future expiry information may label eventual
-- outcome, but all explanatory features are frozen from decision-time evidence.
-- =====================================================================
PRAGMA foreign_keys = ON;

CREATE TABLE counterfactual_rejection_audit_programs_v1 (
    id                                  INTEGER PRIMARY KEY,
    program_key                         TEXT NOT NULL UNIQUE,
    protocol_version                    TEXT NOT NULL,
    frozen_at                           TEXT NOT NULL,
    frozen_through_session_date         TEXT NOT NULL,
    source_replay_run_id                INTEGER NOT NULL
                                        REFERENCES historical_replay_runs_v1(id),
    cohort_max_expiration               TEXT NOT NULL,
    protocol_state                      TEXT NOT NULL
                                        CHECK (
                                            protocol_state =
                                            'FROZEN_RETROSPECTIVE_DISCOVERY_OUTCOME_PENDING'
                                        ),
    config_hash                         TEXT NOT NULL
                                        CHECK (length(config_hash) = 64),
    config_json                         TEXT NOT NULL
                                        CHECK (json_valid(config_json)),
    discovery_context_json              TEXT NOT NULL
                                        CHECK (json_valid(discovery_context_json)),
    outcome_label_semantics             TEXT NOT NULL
                                        CHECK (
                                            outcome_label_semantics =
                                            'RETROSPECTIVE_EXPIRY_RECONSTRUCTION_ONLY'
                                        ),
    wallet_feature_enabled              INTEGER NOT NULL DEFAULT 0
                                        CHECK (wallet_feature_enabled = 0),
    independent_leg_liquidation_label_enabled
                                        INTEGER NOT NULL DEFAULT 0
                                        CHECK (
                                            independent_leg_liquidation_label_enabled = 0
                                        ),
    p_values_enabled                    INTEGER NOT NULL DEFAULT 0
                                        CHECK (p_values_enabled = 0),
    model_training_enabled              INTEGER NOT NULL DEFAULT 0
                                        CHECK (model_training_enabled = 0),
    admission_change_enabled            INTEGER NOT NULL DEFAULT 0
                                        CHECK (admission_change_enabled = 0),
    decision_enabled                    INTEGER NOT NULL DEFAULT 0
                                        CHECK (decision_enabled = 0)
);

CREATE TABLE counterfactual_rejection_audit_cohort_v1 (
    id                                  INTEGER PRIMARY KEY,
    program_id                          INTEGER NOT NULL
                                        REFERENCES counterfactual_rejection_audit_programs_v1(id),
    proposal_id                         INTEGER NOT NULL
                                        REFERENCES shadow_structure_proposals(id),
    selection_group                     TEXT NOT NULL
                                        CHECK (
                                            selection_group IN (
                                                'ADMITTED_AT_TIME',
                                                'REJECTED_AT_TIME_WALLET_ONLY'
                                            )
                                        ),
    source_admission_decision_id        INTEGER NOT NULL
                                        REFERENCES shadow_admission_decisions(id),
    source_candidate_id                 INTEGER
                                        REFERENCES shadow_candidates(id),
    source_policy_replay_id             INTEGER
                                        REFERENCES historical_policy_replay_v1(id),
    underlying                          TEXT NOT NULL,
    expiration                          TEXT NOT NULL,
    original_decided_at                 TEXT NOT NULL,
    original_reason_code                TEXT NOT NULL,
    intrinsic_risk_usd_minor            INTEGER NOT NULL
                                        CHECK (intrinsic_risk_usd_minor > 0),
    estimated_cost_usd_minor            INTEGER NOT NULL
                                        CHECK (estimated_cost_usd_minor >= 0),
    decision_time_features_json         TEXT NOT NULL
                                        CHECK (json_valid(decision_time_features_json)),
    cohort_role                         TEXT NOT NULL
                                        DEFAULT 'FIXED_HISTORICAL_SELECTION_COHORT'
                                        CHECK (
                                            cohort_role =
                                            'FIXED_HISTORICAL_SELECTION_COHORT'
                                        ),
    UNIQUE(program_id, proposal_id),
    CHECK (
        (
            selection_group = 'ADMITTED_AT_TIME'
            AND source_candidate_id IS NOT NULL
            AND source_policy_replay_id IS NULL
        )
        OR
        (
            selection_group = 'REJECTED_AT_TIME_WALLET_ONLY'
            AND source_candidate_id IS NULL
            AND source_policy_replay_id IS NOT NULL
        )
    )
);

CREATE INDEX idx_counterfactual_rejection_cohort_program_v1
ON counterfactual_rejection_audit_cohort_v1(
    program_id,
    selection_group,
    expiration
);

CREATE TABLE counterfactual_rejection_audit_evaluations_v1 (
    id                                  INTEGER PRIMARY KEY,
    program_id                          INTEGER NOT NULL
                                        REFERENCES counterfactual_rejection_audit_programs_v1(id),
    evaluation_version                  TEXT NOT NULL,
    evaluated_at                        TEXT NOT NULL,
    latest_completed_session_date       TEXT NOT NULL,
    cohort_n                            INTEGER NOT NULL CHECK (cohort_n > 0),
    recovered_label_n                   INTEGER NOT NULL
                                        CHECK (recovered_label_n >= 0),
    unresolved_n                        INTEGER NOT NULL CHECK (unresolved_n >= 0),
    missing_recovery_n                  INTEGER NOT NULL
                                        CHECK (missing_recovery_n >= 0),
    evaluation_state                    TEXT NOT NULL
                                        CHECK (
                                            evaluation_state =
                                            'FINAL_RETROSPECTIVE_DISCOVERY_AUDIT'
                                        ),
    metrics_json                        TEXT NOT NULL
                                        CHECK (json_valid(metrics_json)),
    p_values_enabled                    INTEGER NOT NULL DEFAULT 0
                                        CHECK (p_values_enabled = 0),
    model_training_enabled              INTEGER NOT NULL DEFAULT 0
                                        CHECK (model_training_enabled = 0),
    admission_change_enabled            INTEGER NOT NULL DEFAULT 0
                                        CHECK (admission_change_enabled = 0),
    decision_enabled                    INTEGER NOT NULL DEFAULT 0
                                        CHECK (decision_enabled = 0),
    UNIQUE(program_id, evaluation_version)
);

CREATE TRIGGER trg_counterfactual_rejection_program_no_update_v1
BEFORE UPDATE ON counterfactual_rejection_audit_programs_v1
BEGIN
    SELECT RAISE(
        ABORT,
        'Counterfactual rejection audit programme is immutable.'
    );
END;

CREATE TRIGGER trg_counterfactual_rejection_program_no_delete_v1
BEFORE DELETE ON counterfactual_rejection_audit_programs_v1
BEGIN
    SELECT RAISE(
        ABORT,
        'Counterfactual rejection audit programme cannot be deleted.'
    );
END;

CREATE TRIGGER trg_counterfactual_rejection_cohort_no_update_v1
BEFORE UPDATE ON counterfactual_rejection_audit_cohort_v1
BEGIN
    SELECT RAISE(
        ABORT,
        'Counterfactual rejection audit cohort is immutable.'
    );
END;

CREATE TRIGGER trg_counterfactual_rejection_cohort_no_delete_v1
BEFORE DELETE ON counterfactual_rejection_audit_cohort_v1
BEGIN
    SELECT RAISE(
        ABORT,
        'Counterfactual rejection audit cohort cannot be deleted.'
    );
END;

CREATE TRIGGER trg_counterfactual_rejection_eval_no_update_v1
BEFORE UPDATE ON counterfactual_rejection_audit_evaluations_v1
BEGIN
    SELECT RAISE(
        ABORT,
        'Counterfactual rejection audit evaluation is immutable.'
    );
END;

CREATE TRIGGER trg_counterfactual_rejection_eval_no_delete_v1
BEFORE DELETE ON counterfactual_rejection_audit_evaluations_v1
BEGIN
    SELECT RAISE(
        ABORT,
        'Counterfactual rejection audit evaluation cannot be deleted.'
    );
END;

CREATE VIEW v_counterfactual_rejection_audit_labels_v1 AS
SELECT
    c.id AS cohort_row_id,
    c.program_id,
    c.proposal_id,
    c.selection_group,
    c.source_candidate_id,
    c.source_policy_replay_id,
    c.underlying,
    c.expiration,
    c.original_decided_at,
    c.original_reason_code,
    c.intrinsic_risk_usd_minor,
    c.estimated_cost_usd_minor,
    c.decision_time_features_json,
    hor.id AS outcome_recovery_id,
    hor.recovery_state,
    hor.reason_code AS outcome_reason_code,
    hor.measurement_role,
    hor.outcome_eligible,
    hor.estimated_net_pnl_usd_minor,
    CASE
        WHEN hor.recovery_state = 'RECOVERED'
         AND hor.estimated_net_pnl_usd_minor > 0
            THEN 'RETROSPECTIVE_EXPIRY_RECON_NET_POSITIVE'
        WHEN hor.recovery_state = 'RECOVERED'
         AND hor.estimated_net_pnl_usd_minor = 0
            THEN 'RETROSPECTIVE_EXPIRY_RECON_NET_ZERO'
        WHEN hor.recovery_state = 'RECOVERED'
         AND hor.estimated_net_pnl_usd_minor < 0
            THEN 'RETROSPECTIVE_EXPIRY_RECON_NET_NEGATIVE'
        WHEN hor.recovery_state = 'UNRESOLVED'
            THEN 'UNRESOLVED'
        ELSE 'OUTCOME_PENDING'
    END AS outcome_label
FROM counterfactual_rejection_audit_cohort_v1 AS c
JOIN counterfactual_rejection_audit_programs_v1 AS p
  ON p.id = c.program_id
LEFT JOIN historical_outcome_recovery_v1 AS hor
  ON hor.replay_run_id = p.source_replay_run_id
 AND (
        (
            c.selection_group = 'ADMITTED_AT_TIME'
            AND hor.source_population = 'PROSPECTIVE_ORIGINAL'
            AND hor.source_candidate_id = c.source_candidate_id
        )
        OR
        (
            c.selection_group = 'REJECTED_AT_TIME_WALLET_ONLY'
            AND hor.source_population = 'RETROSPECTIVE_POLICY_REPLAY'
            AND hor.policy_replay_id = c.source_policy_replay_id
        )
    );

INSERT INTO schema_version(version, applied_at)
SELECT 33, strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
WHERE NOT EXISTS (
    SELECT 1
    FROM schema_version
    WHERE version = 33
);
