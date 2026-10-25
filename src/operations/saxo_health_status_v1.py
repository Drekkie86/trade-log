"""Broker-isolated, read-only status adapter for the Christiania operator UI.

The command deck must not import Saxo's trading API or possess any order
submission route. Only the sanitized health dataclass crosses this boundary.
"""
from __future__ import annotations

from src.providers.saxo_live_health_v1 import probe_saxo_live

__all__ = ["probe_saxo_live"]
