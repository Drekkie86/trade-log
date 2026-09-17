from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_release_receiver_rolls_back_on_session_hangup():
    receiver = (
        ROOT / "deploy/receive_release.sh"
    ).read_text(encoding="utf-8")

    assert "trap 'rollback $?' ERR INT TERM HUP" in receiver
    assert receiver.count("trap - ERR INT TERM HUP") == 2

    assert "trap 'rollback $?' ERR INT TERM\n" not in receiver