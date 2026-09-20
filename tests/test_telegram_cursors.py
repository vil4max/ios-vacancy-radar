from __future__ import annotations

from storage.telegram_cursors import apply_cursor_updates


def test_cursor_updates_only_move_forward() -> None:
    cursors = {"hirifyme_bot": 10}
    assert apply_cursor_updates(cursors, {"hirifyme_bot": 9}) is False
    assert cursors == {"hirifyme_bot": 10}

    assert apply_cursor_updates(cursors, {"hirifyme_bot": 11}) is True
    assert cursors == {"hirifyme_bot": 11}
