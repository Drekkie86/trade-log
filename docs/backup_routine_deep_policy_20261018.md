# Christiania backup verification policy — 18 October 2026

## Motivation

The 17 October production VACUUM INTO snapshot copied approximately 30 GiB in
7m38s with the daemon active; a subsequent full SQLite integrity_check was
still running after 90 minutes and hit 5 GiB RAM. The operator stopped only
the transient verification unit. It is inactive; the incomplete file was not
promoted. Production remains on schema 34; main has schema 36.

A routine copy and deep SQLite audit have different evidence. Do not label
routine checks as full integrity checks.

## Routine acceptance (new backups)

* Snapshot: a single consistent WAL-aware VACUUM INTO read transaction,
  deadline 1800s, no live schema changes.
* Verification: read-only exact schema check, PRAGMA quick_check(1), and
  PRAGMA foreign_key_check (fail on first violation), progress-handler
  deadline 900s. **quick_check is not integrity_check.** The hard systemd
  runtime deadline must exceed the component budget and bound blocked I/O.
* Bytes: SHA-256 entire snapshot (900s cooperative deadline).
* Promotion: atomic rename, fsynced sidecar manifest, explicit level
  `routine`, `quick_check: "ok"`, `integrity_check: null`, FK count zero.
  Failure must not leave a promoted backup without valid evidence.
* Compression: require source evidence matching its whole-file hash; gzip
  roundtrip decompressed hash must match source hash; hash compressed bytes,
  atomically publish manifest format v2. The gzip is labelled `routine`
  and **must not** be re-described as deep-verified.
* Protection: never automatically pre-prune or post-prune existing verified
  recovery points during a routine backup. Bounded disk-reserve checks fail
  closed; a separate audited retention policy is still required.

Legacy compressed manifest v1 remains understood as deep-checked ONLY when it
contains full `integrity_check: "ok"`, schema and FK evidence.

## Independent deep audit / recovery acceptance

* Separate scheduled off-peak, bounded, resource-limited run;
  `PRAGMA integrity_check` on a restored copy, full schema and foreign-key
  verification, complete bytes, and representative application/research state.
* Report measured recovery time, provenance, RPO/RTO, and hardware.
* Do not strengthen the label merely because gzip SHA/roundtrip succeeded.
* Off-host immutable/object-storage restoration is an additional unsatisfied
  acceptance check (#113), not proved by a separate mounted Hetzner volume.

## One-off schema-34 recovery of the stopped copy

Use `christiania_resume_v34_snapshot_20261018.py` with its paired
`christiania_volume_v34_recovery_snapshot.py` **from the same reviewed
commit**. It targets exactly
`.christiania_backup_20261017T203934Z.incomplete.db` on the separately
mounted volume. It refuses changed schema, missing older recovery points,
symlinks, filename collisions, changing source file, corrupt quick check,
foreign-key violations or absent SHA-256. It does **not** run another VACUUM.

Once the resumed snapshot is independently accepted as routine verified,
`christiania_compress_v34_routine_20261018.py` compresses it with recorded
source, archive and roundtrip hashes, preserving older recovery points. These
two jobs MUST be sequential, detached, bounded by systemd and observed
through their status JSON and systemd result; never run alongside the heavy
release performance benchmark. A restored copy must still pass the deep
acceptance drill before claiming deep verification.

## Operational state on entry

* Legacy `christiania-backup.timer` disabled, and MUST stay so until the
  corrected installed backend and recurring job are configured.
* App, daemon and Theta active at latest 18 Oct 00:48 CEST check.
* Root 01 Oct/08 Oct plain copies plus independent-volume 08 Oct compressed
  copy present; the 17 Oct incomplete copy is **not** verified.
* Do not perform schema 35/36 deployment until fresh recovery and
  rollback readiness are demonstrated.
* A follow-up scheduled-unit patch runs `backup_christiania.py
  --compress-after`: first resume any incomplete compression of a newly
  sidecar-verified routine copy, then evaluate whether another snapshot is
  due, and immediately compress a successful new snapshot. A failure
  prevents another large copy and preserves the plaintext recovery point.
  The existing separate compression timer must remain disabled during this
  transition. No compression of old unmanifested plaintext is automatic.
* Retention economics, verified offsite copies, timer installation and
  configuration, root-volume cleanup, full restore and release performance
  proof remain **incomplete** until independently demonstrated. A
  compressed source is not an off-host backup just because it is small.

See GitHub issue #113 for the operational acceptance backlog. PR #129 / migration
037 is separate and must not be deployed as part of the backup fix.
