# Christiania V1 Release Manifest

`python christiania_release.py manifest --json` produces the machine-readable release fingerprint.

It records the V1 semantic version, release channel, Git SHA/clean state, schema version, a SHA-256 fingerprint of the complete migration chain, a SHA-256 fingerprint of the quantitative model registry, Python/platform identity and the installed versions of critical runtime dependencies.

The manifest intentionally contains no provider credentials or OIDC secrets.
