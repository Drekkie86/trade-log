# Archive

Research code, scripts, tests, Streamlit pages and preregistration documents
that are no longer part of the running Christiania app.

Selection rule: everything that the live entry points (the app, the daemon,
the systemd services and the release/backup/ops tooling) do **not** import was
moved here with `git mv`, so `git log --follow` still shows its full history.
Paths mirror their original location (`archive/src/research/x.py` was
`src/research/x.py`).

Nothing here is imported or tested. To revive a module, `git mv` it back to its
original path together with its tests in `archive/tests/`.
