"""Stable Christiania database-repository import surface.

The implementation lives in :mod:`src.database.repository_impl`; this facade
owns the active schema contract. Keeping the version contract small and
explicit prevents schema-only changes from rewriting thousands of unrelated
repository lines while preserving every existing import path and function
object.
"""

from src.database import repository_impl as _impl


EXPECTED_SCHEMA_VERSION = 34
_impl.EXPECTED_SCHEMA_VERSION = EXPECTED_SCHEMA_VERSION

# Re-export the complete implementation surface, including private helpers used
# by existing tests/internal modules. Function objects retain repository_impl as
# their globals; the schema constant above is synchronized there before export.
for _name in dir(_impl):
    if _name.startswith("__"):
        continue
    globals()[_name] = getattr(_impl, _name)

# The loop also exports the implementation's synchronized value, but state it
# again here so the facade remains the authoritative schema contract.
EXPECTED_SCHEMA_VERSION = 34

__all__ = [
    name
    for name in globals()
    if not name.startswith("__")
    and name not in {"_impl", "_name"}
]
