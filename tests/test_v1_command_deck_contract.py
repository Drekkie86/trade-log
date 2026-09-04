from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_v1_command_deck_has_no_broker_order_path():
    inspected = [
        ROOT / "app.py",
        ROOT / "src" / "dashboard" / "read_model.py",
        ROOT / "src" / "operations" / "sqlite_runtime.py",
    ]

    forbidden = [
        "src.providers.saxo",
        "place_order(",
        "send_order(",
        "execute_order(",
        "submit_order(",
    ]

    combined = "\n".join(
        path.read_text(
            encoding="utf-8"
        )
        for path in inspected
    )

    for token in forbidden:
        assert token not in combined


def test_command_deck_labels_observations_as_non_signal():
    app = (
        ROOT / "app.py"
    ).read_text(
        encoding="utf-8"
    )

    assert "OBSERVATIONAL ONLY" in app
    assert "not trade signals" in app
    assert "No broker-order path" in app


def test_cloud_sqlite_docs_defer_postgres():
    doc = (
        ROOT
        / "docs"
        / "operations"
        / "V1_CLOUD_SQLITE_COMMAND_DECK.md"
    ).read_text(
        encoding="utf-8"
    )

    assert "PostgreSQL is deliberately deferred" in doc
    assert "single-writer" in doc
    assert "read-only" in doc

def test_sqlite_runtime_sidecars_are_ignored():
    ignore = (
        ROOT / ".gitignore"
    ).read_text(
        encoding="utf-8"
    )

    assert "*.db-wal" in ignore
    assert "*.db-shm" in ignore
    assert "*.db-journal" in ignore


def test_app_command_deck_uses_short_cache_and_force_refresh():
    app = (
        ROOT / "app.py"
    ).read_text(
        encoding="utf-8"
    )

    assert "@st.cache_data(ttl=30)" in app
    assert "st.cache_data.clear()" in app


def test_command_deck_exposes_market_and_daemon_health():
    app = (
        ROOT / "app.py"
    ).read_text(
        encoding="utf-8"
    )

    assert '"Market clock"' in app
    assert '"Daemon health"' in app
