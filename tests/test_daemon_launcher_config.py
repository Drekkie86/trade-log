import pytest

from run_christiania_daemon import (
    LOCAL_FALLBACK_SYMBOLS,
    configured_symbols,
)
from src.research.research_daemon import (
    ResearchDaemonError,
)


def test_configured_symbols_uses_local_fallback(monkeypatch):
    monkeypatch.delenv(
        "CHRISTIANIA_SYMBOLS",
        raising=False,
    )

    assert configured_symbols() == LOCAL_FALLBACK_SYMBOLS


def test_configured_symbols_parses_cloud_universe(monkeypatch):
    monkeypatch.setenv(
        "CHRISTIANIA_SYMBOLS",
        "aapl, msft, spy",
    )

    assert configured_symbols() == [
        "AAPL",
        "MSFT",
        "SPY",
    ]


def test_configured_symbols_rejects_duplicates(monkeypatch):
    monkeypatch.setenv(
        "CHRISTIANIA_SYMBOLS",
        "AAPL,aapl",
    )

    with pytest.raises(
        ResearchDaemonError,
        match="duplicates",
    ):
        configured_symbols()
