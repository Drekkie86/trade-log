-- =====================================================================
-- Christiania — migration 017
--
-- Shadow-mark measurement semantics.
--
-- Existing shadow marks are independent-leg liquidation stress marks:
-- long legs are valued at bid and short legs at ask. That is deliberately
-- conservative, but it is not a coherent package-execution outcome and may
-- exceed the theoretical expiry max-loss bound because bid/ask crossing and
-- legging costs are outside that payoff bound.
--
-- Preserve every historical mark unchanged while making its research role
-- explicit and preventing accidental use as validated edge-outcome evidence.
-- =====================================================================

PRAGMA foreign_keys = ON;

ALTER TABLE shadow_mark_observations
ADD COLUMN measurement_role TEXT NOT NULL
DEFAULT 'INDEPENDENT_LEG_LIQUIDATION_STRESS'
CHECK (
    measurement_role IN (
        'INDEPENDENT_LEG_LIQUIDATION_STRESS',
        'VALIDATED_PACKAGE_OUTCOME'
    )
);

ALTER TABLE shadow_mark_observations
ADD COLUMN outcome_eligible INTEGER NOT NULL
DEFAULT 0
CHECK (outcome_eligible IN (0, 1));

INSERT INTO schema_version (
    version,
    applied_at
)
SELECT
    17,
    strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
WHERE NOT EXISTS (
    SELECT 1
    FROM schema_version
    WHERE version = 17
);
