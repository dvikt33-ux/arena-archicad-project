"""Regression tests for encoded provisional URLs and rendered deleted restores."""
from __future__ import annotations

import os
from pathlib import Path

os.environ["USERPROFILE"] = str(Path(__file__).resolve().parent)
import dispatcher


class Page:
    url = "https://chatgpt.com/c/4f943fa5-39fa-4b25-95f8-e06ea1ffabed"


def main() -> None:
    literal = "https://chatgpt.com/c/local-chatgpt:temporary-57"
    encoded_upper = "https://chatgpt.com/c/local-chatgpt%3Atemporary-57"
    encoded_lower = "https://chatgpt.com/c/local-chatgpt%3atemporary-57"
    for url in (literal, encoded_upper, encoded_lower):
        assert dispatcher.is_provisional_control_url(url) is True
        assert dispatcher.is_durable_control_url(url) is False

    record = {"chatgpt_control_url": "https://chatgpt.com/c/WEB:4f943fa5-39fa-4b25-95f8-e06ea1ffabed"}
    ready = [{"role": "assistant", "text": "CONTROL READY"}]
    assert dispatcher.canonicalization_eligible(record, ready, encoded_upper) is False
    assert dispatcher.canonicalization_eligible(record, ready, "https://chatgpt.com/c/4f943fa5-39fa-4b25-95f8-e06ea1ffabed") is True

    original_messages = dispatcher.chatgpt_messages
    original_composer = dispatcher.composer_is_ready
    original_unavailable = dispatcher.page_shows_unavailable
    try:
        dispatcher.chatgpt_messages = lambda _page: ready
        dispatcher.composer_is_ready = lambda _page: True
        dispatcher.page_shows_unavailable = lambda _page: True
        messages, composer, accepted = dispatcher._inspect_restore(
            Page(), record["chatgpt_control_url"], "", Page.url
        )
        assert messages == ready and composer is True and accepted is False
    finally:
        dispatcher.chatgpt_messages = original_messages
        dispatcher.composer_is_ready = original_composer
        dispatcher.page_shows_unavailable = original_unavailable

    assert dispatcher.hard_unavailable_text("Чат был удалён. Начните новый чат.") is True
    print("test_control_followup: OK")


if __name__ == "__main__":
    main()
