# Quality Gate v1.1 repair

This repair corrects two false assumptions discovered by the first real
quality-gate run.

1. Pytest collision detection now fails only when an outside `test_*.py`
   shares a basename with a canonical module under `tests/`. This preserves
   the protection against the recurring `payload/test_x.py` import collision
   without rejecting the legacy root diagnostic `test_native_v6_schema.py`.

2. Fresh-database verification now reads the version established by
   `trade_log_schema.sql` first, then applies only numbered migrations newer
   than that native schema version. The current native schema already contains
   changes from migrations 002–006, so replaying 002 onward caused the
   `duplicate column name: is_paper` false failure.

These are quality-gate corrections only. Production schema, persistence,
research logic and the real database are untouched.
