-- =====================================================================
-- Christiania — migration 030
--
-- Historical policy replay and outcome recovery.
--
-- Purpose:
--   * Recover useful evidence that the old fixed-EUR-500 research gate hid.
--   * Preserve the original prospective records exactly as they happened.
--   * Never relabel a retrospective reconstruction as a prospective decision.
--   * Never promote reconstructed marks/outcomes into validated package
--     outcomes.
--
-- The replay population is separate from shadow_candidates. Historical
-- wallet-blocked proposals are not inserted into the live prospective
-- lifecycle after the fact.
-- =====================================================================
PRAGMA foreign_keys = ON;

CREATE TABLE historical_replay_runs_v1 (
    id                         INTEGER PRIMARY KEY,
    replay_version             TEXT NOT NULL UNIQUE,
    created_at                 TEXT NOT NULL,
    source_policy_version      TEXT NOT NULL,
    target_policy_version      TEXT NOT NULL,
    no_lookahead_contract      TEXT NOT NULL,
    scope_json                 TEXT NOT NULL,
    notes                      TEXT,
    CHECK(length(trim(replay_version)) > 0),
    CHECK(length(trim(source_policy_version)) > 0),
    CHECK(length(trim(target_policy_version)) > 0),
    CHECK(length(trim(no_lookahead_contract)) > 0),
    CHECK(json_valid(scope_json))
);

CREATE TRIGGER trg_historical_replay_runs_no_update_v1
BEFORE UPDATE ON historical_replay_runs_v1
BEGIN
    SELECT RAISE(ABORT, 'Historical replay runs are immutable evidence.');
END;

CREATE TRIGGER trg_historical_replay_runs_no_delete_v1
BEFORE DELETE ON historical_replay_runs_v1
BEGIN
    SELECT RAISE(ABORT, 'Historical replay runs cannot be deleted.');
END;


CREATE TABLE historical_policy_replay_v1 (
    id                              INTEGER PRIMARY KEY,
    replay_run_id                   INTEGER NOT NULL
                                    REFERENCES historical_replay_runs_v1(id),
    original_admission_decision_id  INTEGER NOT NULL
                                    REFERENCES shadow_admission_decisions(id),
    proposal_id                     INTEGER NOT NULL
                                    REFERENCES shadow_structure_proposals(id),
    original_fx_observation_id      INTEGER NOT NULL
                                    REFERENCES fx_observations(id),
    population                      TEXT NOT NULL
                                    DEFAULT 'RETROSPECTIVE_POLICY_REPLAY',
    original_decision               TEXT NOT NULL,
    original_reason_code            TEXT NOT NULL,
    original_decided_at             TEXT NOT NULL,
    counterfactual_decision         TEXT NOT NULL,
    counterfactual_reason_code      TEXT NOT NULL,
    target_risk_policy_version      TEXT NOT NULL,
    proposal_max_loss_usd_minor     INTEGER NOT NULL,
    estimated_cost_usd_minor        INTEGER NOT NULL,
    intrinsic_risk_usd_minor        INTEGER NOT NULL,
    converted_max_loss_eur_minor    INTEGER NOT NULL,
    estimated_cost_eur_minor        INTEGER NOT NULL,
    intrinsic_risk_eur_minor        INTEGER NOT NULL,
    evidence_json                   TEXT NOT NULL,
    UNIQUE(replay_run_id, original_admission_decision_id),
    CHECK(population = 'RETROSPECTIVE_POLICY_REPLAY'),
    CHECK(original_decision = 'BLOCKED'),
    CHECK(counterfactual_decision IN ('WOULD_ADMIT','WOULD_BLOCK')),
    CHECK(proposal_max_loss_usd_minor >= 0),
    CHECK(estimated_cost_usd_minor >= 0),
    CHECK(intrinsic_risk_usd_minor >= proposal_max_loss_usd_minor),
    CHECK(converted_max_loss_eur_minor >= 0),
    CHECK(estimated_cost_eur_minor >= 0),
    CHECK(intrinsic_risk_eur_minor >= converted_max_loss_eur_minor),
    CHECK(json_valid(evidence_json))
);

CREATE INDEX idx_historical_policy_replay_proposal_v1
ON historical_policy_replay_v1(proposal_id);

CREATE TRIGGER trg_historical_policy_replay_no_update_v1
BEFORE UPDATE ON historical_policy_replay_v1
BEGIN
    SELECT RAISE(ABORT, 'Historical policy replay evidence is immutable.');
END;

CREATE TRIGGER trg_historical_policy_replay_no_delete_v1
BEFORE DELETE ON historical_policy_replay_v1
BEGIN
    SELECT RAISE(ABORT, 'Historical policy replay evidence cannot be deleted.');
END;


CREATE TABLE historical_replay_marks_v1 (
    id                              INTEGER PRIMARY KEY,
    policy_replay_id                INTEGER NOT NULL
                                    REFERENCES historical_policy_replay_v1(id),
    proposal_id                     INTEGER NOT NULL
                                    REFERENCES shadow_structure_proposals(id),
    research_run_id                 INTEGER NOT NULL
                                    REFERENCES research_runs(id),
    snapshot_id                     INTEGER
                                    REFERENCES market_snapshots(id),
    observed_at                     TEXT NOT NULL,
    quality_state                   TEXT NOT NULL,
    structure_mark_usd_minor        INTEGER,
    gross_pnl_usd_minor             INTEGER,
    estimated_net_pnl_usd_minor     INTEGER,
    gross_pnl_eur_minor             INTEGER,
    estimated_net_pnl_eur_minor     INTEGER,
    measurement_role                TEXT NOT NULL
                                    DEFAULT 'RETROSPECTIVE_CONSERVATIVE_LIQUIDATION_REPLAY',
    outcome_eligible                INTEGER NOT NULL DEFAULT 0,
    evidence_json                   TEXT NOT NULL,
    UNIQUE(policy_replay_id, research_run_id),
    CHECK(quality_state IN (
        'COMPLETE_RECONSTRUCTED_CONSERVATIVE_LIQUIDATION',
        'INCOMPLETE_LEG_MARK',
        'ENTRY_PRICING_UNAVAILABLE',
        'INVALID_REPLAY_MARK'
    )),
    CHECK(measurement_role = 'RETROSPECTIVE_CONSERVATIVE_LIQUIDATION_REPLAY'),
    CHECK(outcome_eligible = 0),
    CHECK(json_valid(evidence_json))
);

CREATE INDEX idx_historical_replay_marks_replay_time_v1
ON historical_replay_marks_v1(policy_replay_id, observed_at, id);

CREATE INDEX idx_historical_replay_marks_run_v1
ON historical_replay_marks_v1(research_run_id);

CREATE TRIGGER trg_historical_replay_marks_no_update_v1
BEFORE UPDATE ON historical_replay_marks_v1
BEGIN
    SELECT RAISE(ABORT, 'Historical replay marks are immutable evidence.');
END;

CREATE TRIGGER trg_historical_replay_marks_no_delete_v1
BEFORE DELETE ON historical_replay_marks_v1
BEGIN
    SELECT RAISE(ABORT, 'Historical replay marks cannot be deleted.');
END;


CREATE TABLE historical_outcome_recovery_v1 (
    id                              INTEGER PRIMARY KEY,
    replay_run_id                   INTEGER NOT NULL
                                    REFERENCES historical_replay_runs_v1(id),
    source_population               TEXT NOT NULL,
    source_candidate_id             INTEGER
                                    REFERENCES shadow_candidates(id),
    policy_replay_id                INTEGER
                                    REFERENCES historical_policy_replay_v1(id),
    proposal_id                     INTEGER NOT NULL
                                    REFERENCES shadow_structure_proposals(id),
    expiration                      TEXT NOT NULL,
    recovery_state                  TEXT NOT NULL,
    recovery_method                 TEXT NOT NULL,
    reason_code                     TEXT NOT NULL,
    snapshot_id                     INTEGER
                                    REFERENCES market_snapshots(id),
    snapshot_captured_at            TEXT,
    snapshot_provider               TEXT,
    terminal_underlying_price       REAL,
    terminal_structure_value_usd_minor INTEGER,
    entry_cashflow_usd_minor        INTEGER,
    gross_pnl_usd_minor             INTEGER,
    estimated_net_pnl_usd_minor     INTEGER,
    gross_pnl_eur_minor             INTEGER,
    estimated_net_pnl_eur_minor     INTEGER,
    entry_fx_observation_id         INTEGER
                                    REFERENCES fx_observations(id),
    measurement_role                TEXT NOT NULL
                                    DEFAULT 'RETROSPECTIVE_EXPIRY_RECONSTRUCTION',
    outcome_eligible                INTEGER NOT NULL DEFAULT 0,
    evidence_json                   TEXT NOT NULL,
    CHECK(source_population IN (
        'PROSPECTIVE_ORIGINAL',
        'RETROSPECTIVE_POLICY_REPLAY'
    )),
    CHECK(
        (source_population = 'PROSPECTIVE_ORIGINAL'
         AND source_candidate_id IS NOT NULL
         AND policy_replay_id IS NULL)
        OR
        (source_population = 'RETROSPECTIVE_POLICY_REPLAY'
         AND source_candidate_id IS NULL
         AND policy_replay_id IS NOT NULL)
    ),
    CHECK(recovery_state IN ('RECOVERED','UNRESOLVED')),
    CHECK(length(trim(recovery_method)) > 0),
    CHECK(length(trim(reason_code)) > 0),
    CHECK(terminal_underlying_price IS NULL OR terminal_underlying_price >= 0),
    CHECK(measurement_role = 'RETROSPECTIVE_EXPIRY_RECONSTRUCTION'),
    CHECK(outcome_eligible = 0),
    CHECK(json_valid(evidence_json)),
    UNIQUE(
        replay_run_id,
        source_population,
        source_candidate_id,
        policy_replay_id
    )
);

CREATE INDEX idx_historical_outcome_recovery_proposal_v1
ON historical_outcome_recovery_v1(proposal_id);

CREATE TRIGGER trg_historical_outcome_recovery_no_update_v1
BEFORE UPDATE ON historical_outcome_recovery_v1
BEGIN
    SELECT RAISE(ABORT, 'Historical outcome recovery evidence is immutable.');
END;

CREATE TRIGGER trg_historical_outcome_recovery_no_delete_v1
BEFORE DELETE ON historical_outcome_recovery_v1
BEGIN
    SELECT RAISE(ABORT, 'Historical outcome recovery evidence cannot be deleted.');
END;


-- Unified population surface. The labels are scientific provenance, not a
-- ranking. Retrospective policy replay remains visibly separate from the two
-- genuinely prospective admission populations.
CREATE VIEW v_shadow_research_populations_v1 AS
SELECT
    'PROSPECTIVE_ORIGINAL' AS population,
    sad.candidate_id,
    NULL AS policy_replay_id,
    sad.proposal_id,
    ssp.underlying,
    ssp.expiration,
    sad.decided_at AS population_timestamp,
    sad.converted_max_loss_eur_minor,
    sad.estimated_cost_eur_minor,
    sad.reserved_risk_eur_minor AS intrinsic_risk_eur_minor,
    'LEGACY_BANKROLL_POLICY_ADMITTED_AT_THE_TIME' AS provenance
FROM shadow_admission_decisions AS sad
JOIN shadow_structure_proposals AS ssp
  ON ssp.id = sad.proposal_id
WHERE sad.decision = 'ADMITTED'

UNION ALL

SELECT
    'PROSPECTIVE_INTRINSIC_V1' AS population,
    iad.candidate_id,
    NULL AS policy_replay_id,
    iad.proposal_id,
    ssp.underlying,
    ssp.expiration,
    iad.decided_at AS population_timestamp,
    iad.converted_max_loss_eur_minor,
    iad.estimated_cost_eur_minor,
    iad.intrinsic_risk_eur_minor,
    'INTRINSIC_RISK_POLICY_ADMITTED_AT_THE_TIME' AS provenance
FROM shadow_intrinsic_admission_decisions_v1 AS iad
JOIN shadow_structure_proposals AS ssp
  ON ssp.id = iad.proposal_id
WHERE iad.decision = 'ADMITTED'

UNION ALL

SELECT
    'RETROSPECTIVE_POLICY_REPLAY' AS population,
    NULL AS candidate_id,
    hpr.id AS policy_replay_id,
    hpr.proposal_id,
    ssp.underlying,
    ssp.expiration,
    hpr.original_decided_at AS population_timestamp,
    hpr.converted_max_loss_eur_minor,
    hpr.estimated_cost_eur_minor,
    hpr.intrinsic_risk_eur_minor,
    'COUNTERFACTUAL_REPLAY_FROM_IMMUTABLE_WALLET_BLOCK_EVIDENCE' AS provenance
FROM historical_policy_replay_v1 AS hpr
JOIN shadow_structure_proposals AS ssp
  ON ssp.id = hpr.proposal_id
WHERE hpr.counterfactual_decision = 'WOULD_ADMIT';


INSERT INTO schema_version(version, applied_at)
SELECT
    30,
    strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
WHERE NOT EXISTS (
    SELECT 1 FROM schema_version WHERE version = 30
);
