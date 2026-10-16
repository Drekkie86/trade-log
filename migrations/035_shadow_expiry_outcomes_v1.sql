-- =====================================================================
-- Christiania — migration 035
--
-- Prospective expiry-intrinsic outcomes for live-admitted shadow candidates.
--
-- Problem being closed: no production code path has ever written a
-- shadow_mark_observations row with measurement_role =
-- 'VALIDATED_PACKAGE_OUTCOME'. The lifecycle therefore closes every candidate
-- at expiration but can never score one, validated_outcomes is 0 by
-- construction, and the operator has no measurable signal of whether the
-- suggested structures made or lost money.
--
-- A defined-risk option structure held to expiry has a deterministic payoff
-- given the terminal underlying price. That payoff needs no leg-by-leg quote
-- crossing, so it is free of the liquidity-stress contamination that made the
-- intraday marks ineligible as outcomes. This table records that payoff, once
-- per candidate, computed from the entry cashflow persisted at admission and
-- the last stored underlying observation of the expiry session.
--
-- Honesty constraints encoded in the schema:
--   * settlement_basis is pinned to the one basis actually implemented. The
--     terminal price is the last daemon-sampled underlying price of the expiry
--     session, NOT the official settlement value. A later migration may add a
--     stronger basis as a new value; existing rows are never rewritten.
--   * measurement_role is a new, distinct value. These rows are NOT
--     'VALIDATED_PACKAGE_OUTCOME' and the frozen lifecycle scoring contract
--     (SCORED only on validated package outcomes) is left untouched.
--   * UNRESOLVED rows are recorded, so "no outcome" is visible evidence rather
--     than a silent gap.
--   * Rows are immutable and undeletable. One row per candidate.
-- =====================================================================

PRAGMA foreign_keys = ON;

CREATE TABLE shadow_expiry_outcomes_v1 (
    id                                  INTEGER PRIMARY KEY,
    candidate_id                        INTEGER NOT NULL UNIQUE
                                        REFERENCES shadow_candidates(id),
    research_run_id                     INTEGER NOT NULL
                                        REFERENCES research_runs(id),
    recorded_at                         TEXT NOT NULL,
    expiration                          TEXT NOT NULL,
    outcome_state                       TEXT NOT NULL,
    reason_code                         TEXT NOT NULL,
    settlement_basis                    TEXT NOT NULL
                                        DEFAULT 'LAST_STORED_EXPIRY_SESSION_UNDERLYING_SNAPSHOT',
    snapshot_id                         INTEGER
                                        REFERENCES market_snapshots(id),
    snapshot_captured_at                TEXT,
    snapshot_provider                   TEXT,
    terminal_underlying_price           REAL,
    entry_cashflow_usd_minor            INTEGER,
    terminal_structure_value_usd_minor  INTEGER,
    estimated_cost_usd_minor            INTEGER,
    gross_pnl_usd_minor                 INTEGER,
    estimated_net_pnl_usd_minor         INTEGER,
    gross_pnl_eur_minor                 INTEGER,
    estimated_net_pnl_eur_minor         INTEGER,
    max_theoretical_loss_usd_minor      INTEGER,
    entry_fx_observation_id             INTEGER
                                        REFERENCES fx_observations(id),
    entry_eur_to_usd                    REAL,
    measurement_role                    TEXT NOT NULL
                                        DEFAULT 'PROSPECTIVE_EXPIRY_INTRINSIC_V1',
    evidence_json                       TEXT NOT NULL,
    CHECK (outcome_state IN ('RESOLVED', 'UNRESOLVED')),
    CHECK (length(trim(reason_code)) > 0),
    CHECK (settlement_basis = 'LAST_STORED_EXPIRY_SESSION_UNDERLYING_SNAPSHOT'),
    CHECK (measurement_role = 'PROSPECTIVE_EXPIRY_INTRINSIC_V1'),
    CHECK (terminal_underlying_price IS NULL OR terminal_underlying_price >= 0),
    CHECK (entry_eur_to_usd IS NULL OR entry_eur_to_usd > 0),
    CHECK (json_valid(evidence_json)),
    -- A RESOLVED row carries the full arithmetic; an UNRESOLVED row carries none.
    CHECK (
        (outcome_state = 'RESOLVED'
            AND snapshot_id IS NOT NULL
            AND terminal_underlying_price IS NOT NULL
            AND entry_cashflow_usd_minor IS NOT NULL
            AND terminal_structure_value_usd_minor IS NOT NULL
            AND estimated_cost_usd_minor IS NOT NULL
            AND gross_pnl_usd_minor IS NOT NULL
            AND estimated_net_pnl_usd_minor IS NOT NULL
            AND gross_pnl_eur_minor IS NOT NULL
            AND estimated_net_pnl_eur_minor IS NOT NULL
            AND entry_fx_observation_id IS NOT NULL
            AND entry_eur_to_usd IS NOT NULL)
        OR
        (outcome_state = 'UNRESOLVED'
            AND snapshot_id IS NULL
            AND terminal_underlying_price IS NULL
            AND gross_pnl_usd_minor IS NULL
            AND estimated_net_pnl_usd_minor IS NULL
            AND gross_pnl_eur_minor IS NULL
            AND estimated_net_pnl_eur_minor IS NULL)
    ),
    -- Arithmetic identities the writer must satisfy.
    CHECK (
        outcome_state = 'UNRESOLVED'
        OR gross_pnl_usd_minor = entry_cashflow_usd_minor + terminal_structure_value_usd_minor
    ),
    CHECK (
        outcome_state = 'UNRESOLVED'
        OR estimated_net_pnl_usd_minor = gross_pnl_usd_minor - estimated_cost_usd_minor
    )
);

CREATE INDEX idx_shadow_expiry_outcomes_run_v1
ON shadow_expiry_outcomes_v1(research_run_id);

CREATE INDEX idx_shadow_expiry_outcomes_state_v1
ON shadow_expiry_outcomes_v1(outcome_state, expiration);

CREATE TRIGGER trg_shadow_expiry_outcomes_no_update_v1
BEFORE UPDATE ON shadow_expiry_outcomes_v1
BEGIN
    SELECT RAISE(ABORT, 'Shadow expiry outcomes are immutable evidence.');
END;

CREATE TRIGGER trg_shadow_expiry_outcomes_no_delete_v1
BEFORE DELETE ON shadow_expiry_outcomes_v1
BEGIN
    SELECT RAISE(ABORT, 'Shadow expiry outcomes cannot be deleted.');
END;

-- Only candidates that were actually admitted may receive an outcome row.
CREATE TRIGGER trg_shadow_expiry_outcomes_admitted_only_v1
BEFORE INSERT ON shadow_expiry_outcomes_v1
WHEN NOT EXISTS (
    SELECT 1
    FROM v_shadow_admission_decisions_all AS sad
    WHERE sad.candidate_id = NEW.candidate_id
      AND sad.decision = 'ADMITTED'
)
BEGIN
    SELECT RAISE(ABORT, 'Expiry outcome requires an admitted shadow candidate.');
END;

INSERT INTO schema_version(version, applied_at)
SELECT 35, strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
WHERE NOT EXISTS (
    SELECT 1
    FROM schema_version
    WHERE version = 35
);
