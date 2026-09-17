"""Compatibility surface for Christiania shadow outcome collection.

The active implementation is V2, which reads the normalized admission view so
historical bankroll-policy candidates and new account-independent intrinsic-risk
candidates are tracked identically. Keep this import path stable for the daemon
and existing callers.
"""

from src.research.shadow_outcome_collector_v2 import (
    ShadowMarkResult,
    ShadowOutcomeCollectionResult,
    ShadowOutcomeCollectorError,
    collect_shadow_marks,
)

__all__ = [
    "ShadowMarkResult",
    "ShadowOutcomeCollectionResult",
    "ShadowOutcomeCollectorError",
    "collect_shadow_marks",
]
