"""Christiania trade engine: one pipeline from option chain to ranked trades.

chain -> defined-risk structures -> model distributions -> net EV after costs
-> filter -> rank -> picks -> settlement -> track record.

The engine never places orders. Every surfaced trade is logged and settled so
the track record, not the model, decides whether the engine makes money.
"""

ENGINE_VERSION = "CHRISTIANIA_ENGINE_V1"
