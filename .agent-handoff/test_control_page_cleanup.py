"""Regression tests for dispatcher-owned CONTROL page cleanup."""

import importlib.util
import logging.handlers
from pathlib import Path


CORE = Path(__file__).with_name("dispatcher.py")
class _NoFileHandler(logging.Handler):
    def __init__(self, *args, **kwargs):
        super().__init__()

logging.handlers.RotatingFileHandler = _NoFileHandler
spec = importlib.util.spec_from_file_location("dispatcher_cleanup_test", CORE)
dispatcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dispatcher)


class Page:
    def __init__(self, url, name=""):
        self.url = url
        self.name = name
        self.closed = False

    def evaluate(self, script, *args):
        if "window.name" in script and args:
            self.name = args[0]
        if "window.name" in script:
            return self.name
        return "visible"

    def close(self):
        self.closed = True


class Context:
    def __init__(self, pages):
        self.pages = pages


class Browser:
    def __init__(self, pages):
        self.contexts = [Context(pages)]


def test_repeated_cleanup_does_not_grow_service_pages():
    old = Page("https://chatgpt.com/c/old")
    restore = Page("https://chatgpt.com/", dispatcher.RESTORE_PAGE_MARK)
    replacement = Page("https://chatgpt.com/", dispatcher.REBIND_REPLACEMENT_PAGE_MARK)
    user = Page("https://chatgpt.com/c/user")
    active = Page("https://chatgpt.com/c/new")
    browser = Browser([old, restore, replacement, user, active])

    for _ in range(4):
        dispatcher.close_control_service_pages(browser, keep=active, old_url=old.url)

    assert old.closed
    assert restore.closed
    assert replacement.closed
    assert not user.closed
    assert not active.closed


def test_failed_temporary_page_is_owned_and_closeable():
    temporary = Page("https://chatgpt.com/", dispatcher.REBIND_REPROVISION_PAGE_MARK)
    browser = Browser([temporary])
    dispatcher.close_control_service_pages(browser)
    assert temporary.closed


if __name__ == "__main__":
    test_repeated_cleanup_does_not_grow_service_pages()
    test_failed_temporary_page_is_owned_and_closeable()
    print("test_control_page_cleanup: OK")
