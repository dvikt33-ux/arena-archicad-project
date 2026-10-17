"""Regression for multiple DOM-proven CONTROL wake/ACK pairs.

Mock facts cover the Python boundary. The installer separately runs the real
JavaScript scanner against the existing CONTROL CDP page before any restart.
"""
from __future__ import annotations
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import control_reply_handoff as reader

def pair(turn: int, payload: str = "body") -> dict:
    return {"wake": f"Проверь GitHub. turn_id={turn}",
            "answer": f"CONTROL ACK — turn_id={turn}\n{payload}"}

class Page:
    url = "https://chatgpt.com/c/known"
    def __init__(self, pairs=None, error=False):
        self.pairs = pairs
        self.error = error
        self.scanner = ""
    def evaluate(self, script):
        if self.error:
            raise RuntimeError("detached")
        if "return metrics" in script:
            self.scanner = script
            return {"reason": "verified" if self.pairs else "ordering-or-ambiguous",
                    "wakeBubbles": 2, "headingMatches": 2, "replyBodies": 2,
                    "pairs": self.pairs or []}
        return {"boot": True, "ready": True,
                "wakes": ["Проверь GitHub. turn_id=76",
                          "Проверь GitHub. turn_id=78"],
                "turns": []}

class MultiAckTests(unittest.TestCase):
    def test_two_distinct_pairs_preserved_and_latest_read(self):
        page = Page([pair(76, "old result"), pair(78, "new result")])
        diag = {}
        rows = reader._read_verified_ack_pair(page, diag)
        self.assertEqual(len(rows), 4)
        self.assertEqual(reader.parse_control_reply(rows, 76), "old result")
        self.assertEqual(reader.parse_control_reply(rows, 78), "new result")
        self.assertEqual(diag["reason"], "verified")
        self.assertIn("metrics.pairs = candidates.filter", page.scanner)
        self.assertIn("ambiguousTurns", page.scanner)
        self.assertIn("after(wake.el,reply.el)", page.scanner)
        self.assertIn("el.closest(userScope)", page.scanner)

    def test_existing_control_fallback_keeps_chronology(self):
        page = Page([pair(76, "old result"), pair(78, "new result")])
        messages = reader.read_control_marker_fallback(
            page, {"chatgpt_control_url":page.url},
            lambda url: "/c/" in url, lambda a,b:a==b,
            "Служебный чат 01 — CONTROL & BRIDGE",
            "CONTROL READY", lambda _:None)
        self.assertEqual(reader.parse_control_reply(messages, 78), "new result")
        self.assertEqual([m["role"] for m in messages],
                         ["user","assistant","user","assistant","user","assistant"])

    def test_one_pair_still_supported(self):
        self.assertEqual(reader.parse_control_reply(
            reader._read_verified_ack_pair(Page([pair(78)])), 78), "body")

    def test_duplicate_turn_fails_closed_at_python_boundary(self):
        page = Page([pair(78, "first"), pair(78, "second")])
        diag = {}
        self.assertEqual(reader._read_verified_ack_pair(page,diag), [])
        self.assertEqual(diag["reason"], "final-python-ack-validation-failed")

    def test_mismatched_turn_fails_closed(self):
        bad = pair(78)
        bad["answer"] = "CONTROL ACK — turn_id=76\nwrong"
        self.assertEqual(reader._read_verified_ack_pair(Page([pair(76), bad])), [])

    def test_missing_payload_does_not_publish(self):
        self.assertEqual(reader._read_verified_ack_pair(Page([
            pair(76), {"wake":"Проверь GitHub. turn_id=78",
                       "answer":"CONTROL ACK — turn_id=78"}
        ])), [])

    def test_missing_and_unreadable_dom_fail_closed(self):
        self.assertEqual(reader._read_verified_ack_pair(Page([])), [])
        self.assertEqual(reader._read_verified_ack_pair(Page(error=True)), [])

    def test_no_answer_after_pending_wake(self):
        messages = [{"role":"user", "text":"Проверь GitHub. turn_id=78"},
                    {"role":"assistant","text":"CONTROL ACK — turn_id=76\nold"}]
        self.assertIsNone(reader.parse_control_reply(messages,78))

if __name__ == "__main__":
    unittest.main()
