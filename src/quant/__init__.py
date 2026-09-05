"""Christiania V1 quantitative research library.

The package is research-only. It contains no broker-order, candidate-admission,
or live decision path. Models are challengers/diagnostics unless a future
prospective governance package explicitly changes that state.
"""

from src.quant.types import QuantInputError, VanillaOption

__all__ = ["QuantInputError", "VanillaOption"]
