-- =====================================================================
-- Christiania — migration 008
--
-- Reference-first universe + shadow lifecycle persistence.
--
-- Purpose:
--   * enumerate listed contracts independently from market-data snapshots
--   * persist provider observation availability, including absence
--   * persist immutable shadow candidates
--   * persist append-only lifecycle, outcome, and pin events
--   * derive current lifecycle / pin state from event history
-- =====================================================================

PRAGMA foreign_keys = ON;

CREATE TABLE listing_reference_contracts (
    id                          INTEGER PRIMARY KEY,
    research_run_id             INTEGER NOT NULL
                                REFERENCES research_runs(id),
    provider                    TEXT    NOT NULL,
    underlying                  TEXT    NOT NULL,
    provider_contract_id        TEXT    NOT NULL,
    option_symbol               TEXT,
    expiration                  TEXT    NOT NULL,
    strike                      REAL    NOT NULL,
    right                       TEXT    NOT NULL,
    exercise_style              TEXT,
    shares_per_contract         REAL,
    primary_exchange            TEXT,
    additional_underlyings_json TEXT,
    observed_at                 TEXT    NOT NULL,
    ingested_at                 TEXT    NOT NULL,

    UNIQUE (
        research_run_id,
        provider,
        provider_contract_id
    ),

    CHECK (length(trim(provider)) > 0),
    CHECK (length(trim(underlying)) > 0),
    CHECK (length(trim(provider_contract_id)) > 0),
    CHECK (strike >= 0),
    CHECK (right IN ('C', 'P')),
    CHECK (
        shares_per_contract IS NULL
        OR shares_per_contract > 0
    )
);

CREATE INDEX idx_listing_reference_run
ON listing_reference_contracts(research_run_id);

CREATE INDEX idx_listing_reference_identity
ON listing_reference_contracts(
    underlying,
    expiration,
    strike,
    right
);

CREATE TRIGGER trg_listing_reference_no_update
BEFORE UPDATE ON listing_reference_contracts
BEGIN
    SELECT RAISE(
        ABORT,
        'Listing reference contracts are immutable evidence.'
    );
END;

CREATE TRIGGER trg_listing_reference_no_delete
BEFORE DELETE ON listing_reference_contracts
BEGIN
    SELECT RAISE(
        ABORT,
        'Listing reference contracts cannot be deleted.'
    );
END;


CREATE TABLE provider_observation_availability (
    id                       INTEGER PRIMARY KEY,
    reference_contract_id    INTEGER NOT NULL
                             REFERENCES listing_reference_contracts(id),
    provider                 TEXT    NOT NULL,
    evidence_family          TEXT    NOT NULL,
    state                    TEXT    NOT NULL,
    provider_observation_id  TEXT,
    reason_code              TEXT,
    reason_detail            TEXT,
    observed_at              TEXT    NOT NULL,
    raw_timestamp            TEXT,
    ingested_at              TEXT    NOT NULL,

    UNIQUE (
        reference_contract_id,
        provider,
        evidence_family,
        observed_at
    ),

    CHECK (length(trim(provider)) > 0),
    CHECK (length(trim(evidence_family)) > 0),
    CHECK (
        state IN (
            'PRESENT',
            'ABSENT',
            'INVALID',
            'DUPLICATE',
            'ERROR'
        )
    )
);

CREATE INDEX idx_provider_observation_reference
ON provider_observation_availability(reference_contract_id);

CREATE INDEX idx_provider_observation_state
ON provider_observation_availability(
    provider,
    evidence_family,
    state
);

CREATE TRIGGER trg_provider_observation_no_update
BEFORE UPDATE ON provider_observation_availability
BEGIN
    SELECT RAISE(
        ABORT,
        'Provider observation availability is immutable evidence.'
    );
END;

CREATE TRIGGER trg_provider_observation_no_delete
BEFORE DELETE ON provider_observation_availability
BEGIN
    SELECT RAISE(
        ABORT,
        'Provider observation availability cannot be deleted.'
    );
END;


CREATE TABLE shadow_candidates (
    id                          INTEGER PRIMARY KEY,
    research_run_id             INTEGER NOT NULL
                                REFERENCES research_runs(id),
    reference_contract_id       INTEGER NOT NULL
                                REFERENCES listing_reference_contracts(id),
    underlying                  TEXT    NOT NULL,
    scanner_family_id           TEXT    NOT NULL,
    scanner_version             TEXT    NOT NULL,
    scanner_rule_version        TEXT    NOT NULL,
    surfaced_at                 TEXT    NOT NULL,
    entry_quote_observation_id  INTEGER
                                REFERENCES provider_observation_availability(id),
    entry_greek_observation_id  INTEGER
                                REFERENCES provider_observation_availability(id),
    quote_freshness_class       TEXT,
    greek_quality_class         TEXT,
    universe_status             TEXT    NOT NULL,
    structure_id                TEXT    NOT NULL,
    structure_version           TEXT    NOT NULL,
    structure_json              TEXT,
    hypothesis_family           TEXT    NOT NULL,
    hypothesis_version          TEXT    NOT NULL,
    sizing_policy_version       TEXT    NOT NULL,
    max_theoretical_loss_minor  INTEGER NOT NULL,
    cost_model_version          TEXT,
    cost_provenance             TEXT,
    admission_label             TEXT    NOT NULL,

    CHECK (length(trim(underlying)) > 0),
    CHECK (length(trim(scanner_family_id)) > 0),
    CHECK (length(trim(scanner_version)) > 0),
    CHECK (length(trim(scanner_rule_version)) > 0),
    CHECK (
        quote_freshness_class IS NULL
        OR quote_freshness_class IN (
            'FRESH',
            'AGING',
            'STALE',
            'UNKNOWN'
        )
    ),
    CHECK (
        greek_quality_class IS NULL
        OR greek_quality_class IN (
            'GOOD',
            'REVIEW',
            'BAD',
            'UNKNOWN'
        )
    ),
    CHECK (
        universe_status IN (
            'CONSISTENT',
            'DISAGREEMENT_RECORDED',
            'UNUSABLE'
        )
    ),
    CHECK (max_theoretical_loss_minor >= 0),
    CHECK (
        admission_label
        =
        'CANDIDATE — NOT VALIDATED FOR LIVE EDGE TRADING'
    )
);

CREATE INDEX idx_shadow_candidates_run
ON shadow_candidates(research_run_id);

CREATE INDEX idx_shadow_candidates_underlying
ON shadow_candidates(underlying);

CREATE TRIGGER trg_shadow_candidate_reference_same_run
BEFORE INSERT ON shadow_candidates
BEGIN
    SELECT CASE
        WHEN NOT EXISTS (
            SELECT 1
            FROM listing_reference_contracts AS lrc
            WHERE lrc.id = NEW.reference_contract_id
              AND lrc.research_run_id = NEW.research_run_id
              AND lrc.underlying = NEW.underlying
        )
        THEN RAISE(
            ABORT,
            'Shadow candidate reference contract must belong to the same run and underlying.'
        )
    END;
END;

CREATE TRIGGER trg_shadow_candidates_no_update
BEFORE UPDATE ON shadow_candidates
BEGIN
    SELECT RAISE(
        ABORT,
        'Shadow candidates are immutable after admission.'
    );
END;

CREATE TRIGGER trg_shadow_candidates_no_delete
BEFORE DELETE ON shadow_candidates
BEGIN
    SELECT RAISE(
        ABORT,
        'Shadow candidates cannot be deleted.'
    );
END;


CREATE TABLE shadow_state_events (
    id            INTEGER PRIMARY KEY,
    candidate_id  INTEGER NOT NULL
                  REFERENCES shadow_candidates(id),
    from_state    TEXT,
    to_state      TEXT    NOT NULL,
    occurred_at   TEXT    NOT NULL,
    actor         TEXT    NOT NULL,
    reason_code   TEXT,
    note          TEXT,

    CHECK (
        from_state IS NULL
        OR from_state IN (
            'SURFACED',
            'INVESTIGATED',
            'DECIDED',
            'SHADOW_TRACKED',
            'CLOSED_OR_EXPIRED',
            'SCORED',
            'REJECTED'
        )
    ),
    CHECK (
        to_state IN (
            'SURFACED',
            'INVESTIGATED',
            'DECIDED',
            'SHADOW_TRACKED',
            'CLOSED_OR_EXPIRED',
            'SCORED',
            'REJECTED'
        )
    ),
    CHECK (length(trim(actor)) > 0)
);

CREATE INDEX idx_shadow_state_candidate
ON shadow_state_events(candidate_id, id);

CREATE TRIGGER trg_shadow_state_transition_guard
BEFORE INSERT ON shadow_state_events
BEGIN
    SELECT CASE
        WHEN NOT EXISTS (
            SELECT 1
            FROM shadow_state_events
            WHERE candidate_id = NEW.candidate_id
        )
        AND (
            NEW.from_state IS NOT NULL
            OR NEW.to_state != 'SURFACED'
        )
        THEN RAISE(
            ABORT,
            'First shadow state event must be SURFACED.'
        )
    END;

    SELECT CASE
        WHEN EXISTS (
            SELECT 1
            FROM shadow_state_events
            WHERE candidate_id = NEW.candidate_id
        )
        AND NEW.from_state != (
            SELECT to_state
            FROM shadow_state_events
            WHERE candidate_id = NEW.candidate_id
            ORDER BY id DESC
            LIMIT 1
        )
        THEN RAISE(
            ABORT,
            'Shadow state from_state does not match current state.'
        )
    END;

    SELECT CASE
        WHEN EXISTS (
            SELECT 1
            FROM shadow_state_events
            WHERE candidate_id = NEW.candidate_id
        )
        AND NOT (
            (NEW.from_state = 'SURFACED' AND NEW.to_state = 'INVESTIGATED')
            OR
            (NEW.from_state = 'INVESTIGATED' AND NEW.to_state = 'DECIDED')
            OR
            (NEW.from_state = 'DECIDED' AND NEW.to_state = 'SHADOW_TRACKED')
            OR
            (NEW.from_state = 'DECIDED' AND NEW.to_state = 'REJECTED')
            OR
            (NEW.from_state = 'SHADOW_TRACKED' AND NEW.to_state = 'CLOSED_OR_EXPIRED')
            OR
            (NEW.from_state = 'CLOSED_OR_EXPIRED' AND NEW.to_state = 'SCORED')
        )
        THEN RAISE(
            ABORT,
            'Invalid shadow lifecycle transition.'
        )
    END;
END;

CREATE TRIGGER trg_shadow_state_no_update
BEFORE UPDATE ON shadow_state_events
BEGIN
    SELECT RAISE(
        ABORT,
        'Shadow state events are append-only.'
    );
END;

CREATE TRIGGER trg_shadow_state_no_delete
BEFORE DELETE ON shadow_state_events
BEGIN
    SELECT RAISE(
        ABORT,
        'Shadow state events cannot be deleted.'
    );
END;


CREATE TABLE shadow_outcome_observations (
    id                INTEGER PRIMARY KEY,
    candidate_id      INTEGER NOT NULL
                      REFERENCES shadow_candidates(id),
    horizon           TEXT    NOT NULL,
    provider          TEXT    NOT NULL,
    observed_at       TEXT    NOT NULL,
    raw_timestamp     TEXT,
    bid               REAL,
    ask               REAL,
    mid               REAL,
    underlying_price  REAL,
    pnl_minor         INTEGER,
    return_fraction   REAL,
    quality_state     TEXT,
    evidence_json     TEXT,

    UNIQUE (
        candidate_id,
        horizon
    ),

    CHECK (
        horizon IN (
            'NEXT_ELIGIBLE_SESSION',
            'PLUS_3_SESSIONS',
            'PLUS_5_SESSIONS',
            'TERMINAL_EXPIRY',
            'MFE',
            'MAE'
        )
    ),
    CHECK (length(trim(provider)) > 0),
    CHECK (
        bid IS NULL
        OR bid >= 0
    ),
    CHECK (
        ask IS NULL
        OR ask >= 0
    ),
    CHECK (
        bid IS NULL
        OR ask IS NULL
        OR ask >= bid
    )
);

CREATE INDEX idx_shadow_outcomes_candidate
ON shadow_outcome_observations(candidate_id);

CREATE TRIGGER trg_shadow_outcomes_no_update
BEFORE UPDATE ON shadow_outcome_observations
BEGIN
    SELECT RAISE(
        ABORT,
        'Shadow outcome observations are immutable.'
    );
END;

CREATE TRIGGER trg_shadow_outcomes_no_delete
BEFORE DELETE ON shadow_outcome_observations
BEGIN
    SELECT RAISE(
        ABORT,
        'Shadow outcome observations cannot be deleted.'
    );
END;


CREATE TABLE underlying_pin_events (
    id            INTEGER PRIMARY KEY,
    underlying    TEXT    NOT NULL,
    candidate_id  INTEGER NOT NULL
                  REFERENCES shadow_candidates(id),
    action        TEXT    NOT NULL,
    occurred_at   TEXT    NOT NULL,
    reason        TEXT    NOT NULL,

    CHECK (length(trim(underlying)) > 0),
    CHECK (action IN ('PIN', 'UNPIN')),
    CHECK (length(trim(reason)) > 0)
);

CREATE INDEX idx_underlying_pin_candidate
ON underlying_pin_events(candidate_id, id);

CREATE INDEX idx_underlying_pin_underlying
ON underlying_pin_events(underlying, id);

CREATE TRIGGER trg_underlying_pin_candidate_match
BEFORE INSERT ON underlying_pin_events
BEGIN
    SELECT CASE
        WHEN NOT EXISTS (
            SELECT 1
            FROM shadow_candidates AS sc
            WHERE sc.id = NEW.candidate_id
              AND sc.underlying = NEW.underlying
        )
        THEN RAISE(
            ABORT,
            'Underlying pin must match the shadow candidate underlying.'
        )
    END;
END;

CREATE TRIGGER trg_underlying_pin_alternates
BEFORE INSERT ON underlying_pin_events
BEGIN
    SELECT CASE
        WHEN (
            SELECT action
            FROM underlying_pin_events
            WHERE candidate_id = NEW.candidate_id
            ORDER BY id DESC
            LIMIT 1
        ) = NEW.action
        THEN RAISE(
            ABORT,
            'Underlying pin actions must alternate.'
        )
    END;
END;

CREATE TRIGGER trg_underlying_pin_no_update
BEFORE UPDATE ON underlying_pin_events
BEGIN
    SELECT RAISE(
        ABORT,
        'Underlying pin events are append-only.'
    );
END;

CREATE TRIGGER trg_underlying_pin_no_delete
BEFORE DELETE ON underlying_pin_events
BEGIN
    SELECT RAISE(
        ABORT,
        'Underlying pin events cannot be deleted.'
    );
END;


CREATE VIEW v_reference_snapshot_reconciliation AS
SELECT
    lrc.research_run_id,
    lrc.provider,
    lrc.underlying,
    COUNT(*) AS reference_listed_count,
    SUM(
        CASE
            WHEN EXISTS (
                SELECT 1
                FROM provider_observation_availability AS poa
                WHERE poa.reference_contract_id = lrc.id
                  AND poa.provider = lrc.provider
                  AND poa.evidence_family = 'MASSIVE_SNAPSHOT'
                  AND poa.state = 'PRESENT'
            )
            THEN 1 ELSE 0
        END
    ) AS snapshot_present_count,
    SUM(
        CASE
            WHEN EXISTS (
                SELECT 1
                FROM provider_observation_availability AS poa
                WHERE poa.reference_contract_id = lrc.id
                  AND poa.provider = lrc.provider
                  AND poa.evidence_family = 'MASSIVE_SNAPSHOT'
                  AND poa.state = 'ABSENT'
            )
            THEN 1 ELSE 0
        END
    ) AS snapshot_absent_count,
    CASE
        WHEN COUNT(*) =
            SUM(
                CASE
                    WHEN EXISTS (
                        SELECT 1
                        FROM provider_observation_availability AS poa
                        WHERE poa.reference_contract_id = lrc.id
                          AND poa.provider = lrc.provider
                          AND poa.evidence_family = 'MASSIVE_SNAPSHOT'
                          AND poa.state IN ('PRESENT', 'ABSENT')
                    )
                    THEN 1 ELSE 0
                END
            )
        THEN 1
        ELSE 0
    END AS reference_snapshot_reconciles
FROM listing_reference_contracts AS lrc
GROUP BY
    lrc.research_run_id,
    lrc.provider,
    lrc.underlying;


CREATE VIEW v_shadow_current_state AS
SELECT
    sc.id AS candidate_id,
    (
        SELECT sse.to_state
        FROM shadow_state_events AS sse
        WHERE sse.candidate_id = sc.id
        ORDER BY sse.id DESC
        LIMIT 1
    ) AS current_state
FROM shadow_candidates AS sc;


CREATE VIEW v_underlying_pin_state AS
SELECT
    sc.id AS candidate_id,
    sc.underlying,
    (
        SELECT upe.action
        FROM underlying_pin_events AS upe
        WHERE upe.candidate_id = sc.id
        ORDER BY upe.id DESC
        LIMIT 1
    ) AS latest_action,
    CASE
        WHEN (
            SELECT upe.action
            FROM underlying_pin_events AS upe
            WHERE upe.candidate_id = sc.id
            ORDER BY upe.id DESC
            LIMIT 1
        ) = 'PIN'
        THEN 1
        ELSE 0
    END AS is_pinned
FROM shadow_candidates AS sc;


INSERT INTO schema_version (
    version,
    applied_at
)
SELECT
    8,
    strftime(
        '%Y-%m-%dT%H:%M:%SZ',
        'now'
    )
WHERE NOT EXISTS (
    SELECT 1
    FROM schema_version
    WHERE version = 8
);
