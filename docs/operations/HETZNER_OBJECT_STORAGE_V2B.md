# Christiania Storage V2B — Hetzner Object Storage setup

## Purpose

This guide provisions the off-host immutable target used by Christiania
research-evidence archives.

The bucket is deliberately separate from the production server filesystem.
Objects are uploaded with S3 Object Lock in `COMPLIANCE` mode and are restored
back from the remote object before Christiania records the off-host proof.

## One-time Hetzner setup

1. In Hetzner Console, choose the project that will own the archive bucket.
2. Create an Object Storage bucket in the desired location.
3. **Enable Object Lock while creating the bucket.** It cannot be enabled later
   on a bucket that was created without it.
4. Keep the bucket private.
5. Protect the bucket itself against deletion in Hetzner Console.
6. Generate S3 credentials for the project. Save the secret key immediately;
   Hetzner does not show the secret again later.
7. Use a bucket name without dots so virtual-host TLS addressing remains
   straightforward.

Choose an Object Storage location that is operationally separate from the
production host when practical.

Available Hetzner endpoint shapes are:

- `https://fsn1.your-objectstorage.com`
- `https://nbg1.your-objectstorage.com`
- `https://hel1.your-objectstorage.com`

## Christiania environment

Add the following values to `/etc/christiania/christiania.env`:

```
CHRISTIANIA_EVIDENCE_REMOTE_ENDPOINT=https://<region>.your-objectstorage.com
CHRISTIANIA_EVIDENCE_REMOTE_REGION=<region>
CHRISTIANIA_EVIDENCE_REMOTE_BUCKET=<private-object-lock-bucket>
CHRISTIANIA_EVIDENCE_REMOTE_ACCESS_KEY_ID=<access-key>
CHRISTIANIA_EVIDENCE_REMOTE_SECRET_ACCESS_KEY=<secret-key>
CHRISTIANIA_EVIDENCE_REMOTE_PREFIX=christiania/research-evidence/v1
CHRISTIANIA_EVIDENCE_REMOTE_RETENTION_DAYS=365
```

The secret values must never be committed to Git.

## Validation commands

Check bucket reachability and prove Object Lock:

```
python christiania_ops.py archive-remote-check --json
```

Upload and independently restore-verify one local archive:

```
python christiania_ops.py archive-remote-upload \
  --manifest /var/lib/christiania/evidence-archives/<manifest>.manifest.json \
  --json
```

Re-run the remote proof later:

```
python christiania_ops.py archive-remote-verify \
  --proof /var/lib/christiania/evidence-archives/<archive>.remote-proof.json \
  --json
```

Inventory locally recorded off-host proofs:

```
python christiania_ops.py archive-remote-inventory --json
```

## Pruning boundary

A successful V2B remote proof does not itself delete data.

Hot-row pruning is a separate package and must revalidate the exact object
version IDs and COMPLIANCE retention recorded by the remote proof immediately
before any destructive hot-store operation.
