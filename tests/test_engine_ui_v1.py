"""The four Christiania screens render from a real engine database without errors."""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src.engine.worker import run_engine_step
from src.ui.design import Col, money, table, tone, usd
from tests.test_engine_v1 import ASOF, FakeTheta, history, seed_snapshot

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def test_table_aligns_numbers_and_escapes_text():
    out = table([Col("name", "Name", "l"), Col("v", "Value, $", "r", render=lambda r: money(r["v"]))],
                [{"name": "<b>x</b>", "v": -1234.4}])
    assert "&lt;b&gt;x&lt;/b&gt;" in out
    assert '<td class="r">−1,234</td>' in out
    assert '<th class="r ' in out


def test_currency_and_tone_follow_what_is_displayed():
    assert usd(55, signed=True) == "+$55"
    assert usd(-11.2, signed=True) == "−$11"
    assert money(-0.4) == "0" and tone(-0.4) == ""
    assert tone(-3) == "neg" and tone(3) == "pos"


@pytest.fixture
def engine_db(db_path, monkeypatch):
    seed_snapshot(db_path)
    run_engine_step(theta_client=FakeTheta(history(0.15, n=600)), db_path=db_path,
                    now=ASOF + timedelta(minutes=5))
    monkeypatch.setenv("CHRISTIANIA_DB_PATH", str(db_path))
    return db_path


@pytest.mark.parametrize("page", ["Today's trades", "0DTE", "Track record"])
def test_trade_screens_render(engine_db, page):
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    at.sidebar.radio[0].set_value(page).run()
    assert not at.exception, [e.value for e in at.exception]
    text = " ".join(m.value for m in at.markdown)
    assert 'class="chr-head"' in text
    if page == "Today's trades":
        assert '<table class="chr">' in text and "Combo limit" in text


def test_trade_card_offers_reprice_exit_rule_and_trade_form(engine_db):
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    text = " ".join(m.value for m in at.markdown)
    assert "Expiry day:" in text and "Priced under" in text and "Stress" in text
    labels = {b.label for b in at.button}
    assert "Re-price on live quotes" in labels and "Record trade" in labels
    assert any("Open risk now" in m.value for m in at.markdown)


def test_system_page_reports_history_and_backtest(engine_db):
    at = AppTest.from_file(APP, default_timeout=90)
    at.run()
    at.sidebar.radio[0].set_value("System").run()
    assert not at.exception, [e.value for e in at.exception]
    text = " ".join(m.value for m in at.markdown)
    assert "Price history" in text and "Intraday history" in text and "Backtest" in text
