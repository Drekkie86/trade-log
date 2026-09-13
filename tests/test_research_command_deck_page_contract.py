from pathlib import Path


def test_research_command_deck_page_preserves_discovery_language() -> None:
    root = Path(__file__).resolve().parents[1]
    text = (root / "pages" / "01_Research_Command_Deck.py").read_text(encoding="utf-8")

    assert "Research status is not a trading recommendation" in text
    assert "Hypothesis evaluations" in text
    assert "Prospective evidence accumulation" in text
    assert "academic or historical evidence is a hypothesis source" in text
    assert "validated edge" not in text.lower()
