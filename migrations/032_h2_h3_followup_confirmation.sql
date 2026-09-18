-- =====================================================================
-- Christiania — migration 032
--
-- Separate H2/H3 follow-up confirmation programme.
--
-- This schema deliberately does NOT add another row to the original
-- prospective_research_freeze_v1_runs table and does not replace either
-- v_local_surface_v2_prospective_partition_v1 or v2. The Sep-04 H1-H4
-- prospective clock therefore remains untouched.
-- =====================================================================
PRAGMA foreign_keys = ON;

CREATE TABLE prospective_followup_programs_v1 (
    id                              INTEGER PRIMARY KEY,
    program_key                     TEXT NOT NULL UNIQUE,
    protocol_version                TEXT NOT NULL,
    source_original_freeze_run_id   INTEGER NOT NULL
                                    REFERENCES prospective_research_freeze_v1_runs(id),
    frozen_at                       TEXT NOT NULL,
    frozen_through_session_date     TEXT NOT NULL,
    prospective_start_session_date  TEXT NOT NULL,
    protocol_state                  TEXT NOT NULL
                                    CHECK (
                                        protocol_state =
                                        'FROZEN_FOLLOWUP_OBSERVATION_ONLY'
                                    ),
    config_hash                     TEXT NOT NULL
                                    CHECK (length(config_hash) = 64),
    config_json                     TEXT NOT NULL
                                    CHECK (json_valid(config_json)),
    discovery_context_json          TEXT NOT NULL
                                    CHECK (json_valid(discovery_context_json)),
    p_values_enabled                INTEGER NOT NULL DEFAULT 0
                                    CHECK (p_values_enabled = 0),
    fdr_enabled                     INTEGER NOT NULL DEFAULT 0
                                    CHECK (fdr_enabled = 0),
    admission_enabled               INTEGER NOT NULL DEFAULT 0
                                    CHECK (admission_enabled = 0),
    model_promotion_enabled         INTEGER NOT NULL DEFAULT 0
                                    CHECK (model_promotion_enabled = 0),
    decision_enabled                INTEGER NOT NULL DEFAULT 0
                                    CHECK (decision_enabled = 0),
    CHECK (
        frozen_through_session_date <
        prospective_start_session_date
    )
);

CREATE TABLE prospective_followup_hypotheses_v1 (
    id                                  INTEGER PRIMARY KEY,
    program_id                          INTEGER NOT NULL
                                        REFERENCES prospective_followup_programs_v1(id),
    hypothesis_key                      TEXT NOT NULL,
    description                         TEXT NOT NULL,
    primary_unit                        TEXT NOT NULL,
    primary_metric_family               TEXT NOT NULL,
    minimum_independent_dates           INTEGER NOT NULL
                                        CHECK (minimum_independent_dates = 5),
    serious_review_independent_dates    INTEGER NOT NULL
                                        CHECK (serious_review_independent_dates = 20),
    selection_provenance_json           TEXT NOT NULL
                                        CHECK (json_valid(selection_provenance_json)),
    hypothesis_state                    TEXT NOT NULL
                                        CHECK (
                                            hypothesis_state =
                                            'FROZEN_FOLLOWUP_PROSPECTIVE'
                                        ),
    decision_enabled                    INTEGER NOT NULL DEFAULT 0
                                        CHECK (decision_enabled = 0),
    UNIQUE (program_id, hypothesis_key)
);

CREATE TABLE prospective_followup_evaluations_v1 (
    id                           INTEGER PRIMARY KEY,
    program_id                   INTEGER NOT NULL
                                 REFERENCES prospective_followup_programs_v1(id),
    hypothesis_id                INTEGER NOT NULL
                                 REFERENCES prospective_followup_hypotheses_v1(id),
    hypothesis_key               TEXT NOT NULL,
    evaluation_version           TEXT NOT NULL,
    milestone_date_count         INTEGER NOT NULL
                                 CHECK (milestone_date_count IN (5, 20)),
    evaluated_at                 TEXT NOT NULL,
    evidence_start_session_date  TEXT NOT NULL,
    evidence_end_session_date    TEXT NOT NULL,
    independent_date_count       INTEGER NOT NULL,
    observation_count            INTEGER NOT NULL
                                 CHECK (observation_count >= 0),
    evaluation_state             TEXT NOT NULL
                                 CHECK (
                                     evaluation_state IN (
                                         'DESCRIPTIVE_5_DATE_CHECKPOINT',
                                         'SERIOUS_20_DATE_REVIEW'
                                     )
                                 ),
    metrics_json                 TEXT NOT NULL
                                 CHECK (json_valid(metrics_json)),
    p_values_enabled             INTEGER NOT NULL DEFAULT 0
                                 CHECK (p_values_enabled = 0),
    fdr_enabled                  INTEGER NOT NULL DEFAULT 0
                                 CHECK (fdr_enabled = 0),
    admission_enabled            INTEGER NOT NULL DEFAULT 0
                                 CHECK (admission_enabled = 0),
    model_promotion_enabled      INTEGER NOT NULL DEFAULT 0
                                 CHECK (model_promotion_enabled = 0),
    decision_enabled             INTEGER NOT NULL DEFAULT 0
                                 CHECK (decision_enabled = 0),
    CHECK (independent_date_count = milestone_date_count),
    UNIQUE (
        program_id,
        hypothesis_id,
        evaluation_version,
        milestone_date_count
    )
);

CREATE INDEX idx_prospective_followup_hypothesis_program_v1
ON prospective_followup_hypotheses_v1(program_id, hypothesis_key);

CREATE INDEX idx_prospective_followup_evaluation_program_v1
ON prospective_followup_evaluations_v1(
    program_id,
    hypothesis_id,
    milestone_date_count
);

CREATE TRIGGER trg_prospective_followup_program_no_update_v1
BEFORE UPDATE ON prospective_followup_programs_v1
BEGIN
    SELECT RAISE(
        ABORT,
        'Prospective follow-up programme evidence is immutable.'
    );
END;

CREATE TRIGGER trg_prospective_followup_program_no_delete_v1
BEFORE DELETE ON prospective_followup_programs_v1
BEGIN
    SELECT RAISE(
        ABORT,
        'Prospective follow-up programme evidence cannot be deleted.'
    );
END;

CREATE TRIGGER trg_prospective_followup_hypothesis_no_update_v1
BEFORE UPDATE ON prospective_followup_hypotheses_v1
BEGIN
    SELECT RAISE(
        ABORT,
        'Prospective follow-up hypotheses are immutable.'
    );
END;

CREATE TRIGGER trg_prospective_followup_hypothesis_no_delete_v1
BEFORE DELETE ON prospective_followup_hypotheses_v1
BEGIN
    SELECT RAISE(
        ABORT,
        'Prospective follow-up hypotheses cannot be deleted.'
    );
END;

CREATE TRIGGER trg_prospective_followup_evaluation_no_update_v1
BEFORE UPDATE ON prospective_followup_evaluations_v1
BEGIN
    SELECT RAISE(
        ABORT,
        'Prospective follow-up evaluations are immutable evidence.'
    );
END;

CREATE TRIGGER trg_prospective_followup_evaluation_no_delete_v1
BEFORE DELETE ON prospective_followup_evaluations_v1
BEGIN
    SELECT RAISE(
        ABORT,
        'Prospective follow-up evaluations cannot be deleted.'
    );
END;

-- Fixed-program read surface. It is intentionally independent of the
-- original "latest freeze" partition view.
CREATE VIEW v_h2_h3_followup_partition_v1 AS
SELECT
    d.*,
    o.option_quote_id,
    o.model_run_id,
    r.config_hash AS surface_config_hash,
    p.id AS followup_program_id,
    p.program_key,
    p.frozen_through_session_date,
    p.prospective_start_session_date,
    CASE
        WHEN d.us_session_date <= p.frozen_through_session_date
            THEN 'DISCOVERY_EXCLUDED'
        WHEN d.us_session_date >= p.prospective_start_session_date
            THEN 'FOLLOWUP_PROSPECTIVE'
        ELSE 'BOUNDARY_GAP'
    END AS followup_evidence_phase
FROM v_local_surface_residual_v2_discovery_dataset AS d
JOIN local_surface_residual_v2_observations AS o
  ON o.id = d.observation_id
JOIN local_surface_residual_v2_runs AS r
  ON r.id = o.model_run_id
JOIN prospective_followup_programs_v1 AS p
  ON p.program_key = 'H2_H3_FOLLOWUP_CONFIRMATION_V1';

CREATE VIEW v_prospective_followup_latest_v1 AS
WITH ranked AS (
    SELECT
        e.*,
        ROW_NUMBER() OVER (
            PARTITION BY e.hypothesis_id
            ORDER BY e.milestone_date_count DESC, e.id DESC
        ) AS rn
    FROM prospective_followup_evaluations_v1 AS e
)
SELECT *
FROM ranked
WHERE rn = 1;

INSERT INTO schema_version(version, applied_at)
SELECT 32, strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
WHERE NOT EXISTS (
    SELECT 1
    FROM schema_version
    WHERE version = 32
);
