# Claude full hostile review package

This is the canonical workflow for creating a **complete, reproducible Christiania review bundle** for an external hostile reviewer such as Claude.

The package is intentionally broader than the older pause-point review prompt. It is designed for a repository-wide review of code, quantitative models, research governance, persistence, tests, security, deployment and recovery.

## Design goals

The package must:

- represent one exact Git commit;
- include every Git-tracked file, preserving repository paths;
- include all source, tests, SQL, migrations, research protocols, deployment assets, CI and quantitative model code;
- include per-file SHA-256 hashes and a complete file ledger;
- include Christiania's own quality-gate result as evidence, without treating it as proof of correctness;
- include a syntax/compile evidence capture;
- give the reviewer a strict adversarial prompt and required report structure;
- refuse a dirty working tree;
- refuse a checkout that is not exactly `origin/main`;
- refuse obvious tracked secret/private-key material;
- intentionally exclude untracked production secrets, the live DB, backups and private runtime state.

## Build

From the repository root with the normal Christiania virtual environment active:

```powershell
python .\build_claude_hostile_review_package.py
```

The script runs the full Christiania quality gate by default. This can take time because the gate includes both normal and slow pytest populations.

Output is written to:

```text
review_packages\christiania-hostile-review-<12-char-commit>.zip
review_packages\christiania-hostile-review-<12-char-commit>.zip.sha256
```

`review_packages/` is ignored by Git.

## What to upload to Claude

Upload the generated ZIP. Then tell Claude:

> Start with `START_HERE.md`, then follow `CLAUDE_HOSTILE_REVIEW_FULL_PROMPT.md`. This is a hostile review. Do not optimize for politeness or agreement. Use `MANIFEST.csv` as the completeness ledger and explicitly report anything you could not inspect.

No additional Christiania source files should be needed if the package build succeeded.

## Package contents

The ZIP contains:

- `START_HERE.md`;
- `CLAUDE_HOSTILE_REVIEW_FULL_PROMPT.md`;
- `MANIFEST.csv`;
- `REPO_TREE.txt`;
- `REVIEW_INDEX.md`;
- `GIT_CONTEXT.txt`;
- `QUALITY_GATE.txt`;
- `PYTHON_COMPILEALL.txt`;
- `PACKAGE_METADATA.json`;
- `repository/` with every tracked file from the exact reviewed commit.

## Security / exclusions

Never add live secrets simply to make an external review feel more complete.

The package deliberately does not include:

- `.env`;
- `/etc/christiania/christiania.env`;
- `/etc/christiania/secure-edge.env`;
- OAuth client secrets;
- OAuth cookie secrets;
- API keys;
- SSH keys;
- broker credentials;
- the live production SQLite database;
- production backups;
- private audit exports.

The reviewer should inspect how code and deployment configuration **expect** these resources to be secured. If later runtime review is desired, create a separate sanitized runtime-evidence bundle rather than copying secret-bearing files.

## Review standard

A good hostile review should be able to say all of the following independently:

- whether the software behaves as claimed;
- whether the quantitative math is independently defensible;
- whether statistical evidence can be trusted;
- whether risk outputs are conservative and correctly labelled;
- whether Main Engine and Casino remain isolated;
- whether deployment/recovery can fail safely;
- which claims are not supported by the supplied evidence;
- exactly what must be fixed before any affected capability informs a real bounded-risk trade.

The correct result is allowed to be severe. The purpose is to discover defects before Christiania learns to trust itself.