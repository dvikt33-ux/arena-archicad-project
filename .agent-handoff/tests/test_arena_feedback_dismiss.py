"""Focused no-browser tests for Arena's finished-task feedback overlay."""
from __future__ import annotations

import ast
import unittest
from unittest.mock import patch
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "dispatcher.py"
AST = ast.parse(SOURCE.read_text(encoding="utf-8"))

def functions():
    env = {"ARENA_URL": "https://arena.ai/agent/a1",
           "all_pages": lambda browser: browser}
    logs = []
    env["log"] = logs.append
    env["url_matches"] = lambda url, expected: url == expected or url.startswith(expected + "?")
    for name in ("arena_feedback_visible", "dismiss_arena_completion",
                 "dismiss_visible_arena_feedback"):
        node, = [f for f in AST.body if isinstance(f, ast.FunctionDef) and f.name == name]
        exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])),
                     str(SOURCE), "exec"), env)
    return env, logs

class FakeLocator:
    def __init__(self, page, kind, value, exact=False):
        self.page, self.kind, self.value, self.exact = page, kind, value, exact
    def count(self):
        if self.kind == "marker":
            return int(self.page.feedback and self.value in self.page.prompt)
        if self.kind == "action":
            return int(self.page.feedback and self.value in self.page.actions)
        return 0
    @property
    def first(self):
        return self
    def nth(self, index):
        assert index == 0
        return self
    def is_visible(self):
        return self.count() > 0
    def click(self, timeout=None):
        self.page.clicked.append(self.value)
        if self.kind == "action" and self.value in self.page.actions:
            self.page.feedback = False

class FakePage:
    def __init__(self, feedback=True, url="https://arena.ai/agent/a1",
                 prompt="Эта задача была выполнена успешно?",
                 actions=("Продолжить работу",), active_overlay=True):
        self.feedback, self.url, self.prompt = feedback, url, prompt
        self.active_overlay = active_overlay
        self.actions, self.clicked = actions, []

    def evaluate(self, script):
        # Model the result of active-modal DOM scoping, not global message text.
        assert '[role="dialog"]' in script and "style.position === 'fixed'" in script
        return bool(self.feedback and self.active_overlay)
    def get_by_text(self, label, exact=False):
        if label in ("Эта задача была выполнена успешно?",
                     "Was this task completed successfully?",
                     "Was this task successful?"):
            return FakeLocator(self, "marker", label)
        return FakeLocator(self, "action", label, exact)
    def locator(self, selector):
        # Old HTML buttons must not trigger a Yes/No feedback rating.
        label = "Продолжить работу" if "Продолжить работу" in selector else "Continue working"
        return FakeLocator(self, "action", label)
    def wait_for_timeout(self, ms):
        pass

class ArenaFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.env, self.logs = functions()

    def test_closes_russian_prompt_without_rating(self):
        page = FakePage()
        self.assertTrue(self.env["dismiss_arena_completion"](page))
        self.assertFalse(page.feedback)
        self.assertEqual(page.clicked, ["Продолжить работу"])
        self.assertTrue(any("закрыто" in line for line in self.logs))
        self.assertFalse(self.env["dismiss_arena_completion"](page))
        self.assertEqual(len(page.clicked), 1)

    def test_no_action_without_finished_task_prompt(self):
        page = FakePage(feedback=False)
        self.assertFalse(self.env["dismiss_arena_completion"](page))
        self.assertFalse(page.clicked)

    def test_historical_feedback_text_in_chat_is_not_a_dialog(self):
        # This reproduces the screenshot: normal Arena composer is available
        # but a previous message still contains the completed-task question.
        page = FakePage(feedback=True, active_overlay=False, actions=())
        self.assertFalse(self.env["arena_feedback_visible"](page))
        self.assertFalse(self.env["dismiss_arena_completion"](page))
        self.assertFalse(page.clicked)
        self.assertEqual(self.logs, [])

    def test_must_have_visible_active_overlay_even_when_old_text_remains(self):
        page = FakePage(active_overlay=False)
        self.assertFalse(self.env["dismiss_visible_arena_feedback"]([page]))
        self.assertEqual(page.clicked, [])
        page.active_overlay = True
        self.assertTrue(self.env["dismiss_visible_arena_feedback"]([page]))
        self.assertEqual(page.clicked, ["Продолжить работу"])

    def test_english_prompt(self):
        page = FakePage(prompt="Was this task completed successfully?",
                        actions=("Continue working",))
        self.assertTrue(self.env["dismiss_arena_completion"](page))
        self.assertEqual(page.clicked, ["Continue working"])

    def test_regular_polling_no_navigation_to_wrong_tabs(self):
        wrong = FakePage(url="https://arena.ai/agent/different")
        target = FakePage()
        self.assertTrue(self.env["dismiss_visible_arena_feedback"]([wrong, target]))
        self.assertEqual(wrong.clicked, [])
        self.assertEqual(target.clicked, ["Продолжить работу"])

    def test_stuck_overlay_retries_with_backoff_not_log_spam(self):
        page = FakePage(actions=())
        dismiss = self.env["dismiss_arena_completion"]
        with patch("time.monotonic", side_effect=[100, 101, 104, 105]):
            self.assertFalse(dismiss(page))
            self.assertFalse(dismiss(page))
            self.assertFalse(dismiss(page))
            self.assertFalse(dismiss(page))
        # First and second actual attempts occurred at 100 and 104.
        # The 5-second polling must not generate an endless log torrent.
        self.assertEqual(len(self.logs), 1)
        self.assertIn("автоматический повтор", self.logs[0])
        self.assertEqual(page.clicked, [])

    def test_overlay_reappearing_after_success_is_dismissed_again(self):
        page = FakePage()
        dismiss = self.env["dismiss_arena_completion"]
        self.assertTrue(dismiss(page))
        self.assertFalse(dismiss(page))
        page.feedback = True
        self.assertTrue(dismiss(page))
        self.assertEqual(page.clicked, ["Продолжить работу", "Продолжить работу"])

    def test_no_buttons_yes_no_are_ever_activated(self):
        page = FakePage(actions=("Да", "Нет"))
        dismiss = self.env["dismiss_arena_completion"]
        self.assertFalse(dismiss(page))
        self.assertEqual(page.clicked, [])

    def test_dismissal_failed_keeps_arena_editor_blocked(self):
        page = FakePage(actions=())
        env = dict(self.env)
        env["arena_editor"] = lambda page: self.fail("editor should not be queried")
        fn, = [f for f in AST.body if isinstance(f, ast.FunctionDef)
               and f.name == "send_to_arena"]
        exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])),
                     str(SOURCE), "exec"), env)
        with self.assertRaisesRegex(RuntimeError, "ARENA_INPUT_UNAVAILABLE"):
            env["send_to_arena"](page, "Проверь GitHub. turn_id=77")
        self.assertEqual(page.clicked, [])

    def test_no_arena_open_does_not_create_page(self):
        foreign = FakePage(url="https://chatgpt.com/c/xxx")
        self.assertFalse(self.env["dismiss_visible_arena_feedback"]([foreign]))
        self.assertFalse(foreign.clicked)

if __name__ == "__main__":
    unittest.main()
