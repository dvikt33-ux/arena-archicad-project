"""Focused contract tests for the 2026-10-17 inline Arena feedback card.

The mocked boolean outcomes are not substitutes for the installer's read-only
CDP test against the user's actual Arena DOM.
"""
from __future__ import annotations
import ast
import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "dispatcher.py"
TREE = ast.parse(SOURCE.read_text(encoding="utf-8"))
PREDICATE = next(
    f for f in TREE.body if isinstance(f, ast.FunctionDef)
    and f.name == "arena_feedback_visible"
)

def evaluator():
    env = {}
    exec(compile(ast.fix_missing_locations(
        ast.Module(body=[PREDICATE], type_ignores=[])), str(SOURCE), "exec"), env)
    return env["arena_feedback_visible"]

class FakePage:
    def __init__(self, active=False, throw=False):
        self.active, self.throw = active, throw
        self.script = ""
    def evaluate(self, script):
        self.script = script
        if self.throw:
            raise RuntimeError("page detached")
        return bool(self.active)

class InlineFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.read = evaluator()

    def test_inline_non_modal_card_is_supported(self):
        page = FakePage(active=True)
        self.assertTrue(self.read(page))
        self.assertIn("const compact =", page.script)
        self.assertIn("style.position === 'fixed'", page.script)
        self.assertIn('[role="dialog"]', page.script)

    def test_chat_history_not_treated_as_feedback(self):
        page = FakePage(active=False)
        self.assertFalse(self.read(page))
        self.assertIn('el.closest(history)', page.script)
        self.assertIn("box.closest(history)", page.script)
        self.assertIn('[class*="MarkdownRoot-"]', page.script)
        self.assertIn('conversation-turn', page.script)

    def test_requires_all_three_choices_within_same_card(self):
        page = FakePage()
        self.read(page)
        self.assertIn("continueLabels.has(t)", page.script)
        self.assertIn("yesLabels.has(t)", page.script)
        self.assertIn("noLabels.has(t)", page.script)
        self.assertIn("const labels = textNodes(box)", page.script)

    def test_compact_panel_must_be_visible_and_bounded(self):
        page = FakePage()
        self.read(page)
        for marker in ("r.width < innerWidth * .92",
                       "r.height < innerHeight * .65",
                       "r.bottom <= innerHeight + 8",
                       "r.top < innerHeight"):
            self.assertIn(marker, page.script)

    def test_ambiguous_multiple_cards_fail_closed(self):
        page = FakePage()
        self.read(page)
        self.assertIn("return matchedCards === 1", page.script)
        self.assertIn("const visited = new Set()", page.script)

    def test_read_error_returns_false(self):
        self.assertFalse(self.read(FakePage(throw=True)))

    def test_label_click_count_must_be_unique(self):
        body = SOURCE.read_text(encoding="utf-8")
        start = body.index("def dismiss_arena_completion(page)")
        stop = body.index("def dismiss_visible_arena_feedback(", start)
        clicker = body[start:stop]
        self.assertIn("if count != 1:", clicker)
        self.assertIn("if not arena_feedback_visible(page)", clicker)
        self.assertNotIn('option.first.click(timeout=1500)\n                        click_attempts += 1\n                        page.wait_for_timeout(400)\n                        # No recheck', clicker)

if __name__ == "__main__":
    unittest.main()
