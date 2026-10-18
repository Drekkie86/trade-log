# Christiania independent-volume backup recovery (2026-10-18)

The October 17 20:47:11 UTC v34 VACUUM INTO copy completed successfully, but the old 900-second routine quick_check timed out. Its 32,164,368,384-byte incomplete-named snapshot was never promoted on that evidence.

## Proven October 17 recovery

Pinned one-time tool: christiania_finalize_v34_archive_20261018.py. The script compressed the complete snapshot into christiania_backup_20261017T203934Z.db.gz on the separate recovery volume (4,890,217,931 bytes). It verified gzip CRC and SHA-256 for the full uncompressed payload, restored into a separate SQLite file, checked physical page count/table metadata and v34 schema, and removed only the original incomplete-named temporary snapshot after the restore succeeded. Previous October 8 full-integrity-checked archive/manifest and independent root recovery points were preserved. Available volume headroom became approximately 85 GiB.

**Evidence boundary:** this newer archive has real byte-for-byte restore plus SQLite structural readability, not a complete SQLite integrity_check or foreign_key_check. The manifest explicitly records those tests as absent. The older October 8 anchor retains full integrity-check evidence.

## Permanent independent service

Nightly tool christiania_volume_backup_routine_20261018.py uses read-only-source SQLite VACUUM INTO; 15 GiB free-space reserve; automatic gzip/CRC/SHA round-trip; separate restored-file metadata check; atomic archive/manifest publication; and retention of the newest three nightly archives, never pruning the deep-verified October 8 archive or October 17 rescued copy. Existing incomplete snapshots abort new work rather than quietly consuming another 30 GiB. Results are visible in volume_backup_scheduler_status.json and service logs.

systemd nightly timer christiania-volume-recovery-backup.timer: 00:30 UTC with up to 10 minutes randomized delay; no persistent catch-up. Weekly timer christiania-volume-recovery-audit.timer: Sunday 03:30 UTC plus up to 15 minutes randomized delay. The audit rehashes the compressed archive and restores a separate SQLite file to verify the archive remains readable; reports volume_backup_restore_audit_status.json.

Run as restricted christiania user, with CPU/memory/IO limits, volume-specific write permission, and exclusive cross-job flock. Never disable running app, Theta, or daemon. Legacy root backup/compress timers and the legacy inadequate-root-headroom restore drill should remain disabled to avoid duplicate heavy operations.

Production still runs application v34 at the time of this recovery. GitHub main v36 and Claude PR #129 migration v37 are separate gated releases. This operations-only recovery is not proof that those application migrations are ready. Offsite archival has NOT been reverified, and must not be represented as active.

Previous restore-drill failures also resulted from /etc/christiania/christiania.env being 0600 root:christiania while the unprivileged christiania service was coded to read the file directly. It was corrected to 0640 root:christiania without exposing configuration contents.

Operator check: inspect both systemd ExecMainStatus/Result and durable phase in the JSON status; service Result=success alone is never accepted as evidence.
