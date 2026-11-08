"""Christiania trade engine.

V2 (2026-11-08): sells defined-risk premium where the market's own smile,
shrunk by the underlying's measured variance risk premium, still pays after
costs and a stress shock. V1's forecast models (EWMA/GARCH and resampled
history) were retired after the first backtest: they bought tails against the
smile and lost 21 % of risk over 640 picks.
"""

ENGINE_VERSION = "CHRISTIANIA_ENGINE_V2"
