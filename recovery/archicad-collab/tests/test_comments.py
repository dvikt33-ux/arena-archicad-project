"""Тесты комментариев: локальные ops, пересылка между журналами, applier."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from accollab import comments  # noqa: E402
from accollab.applier import apply_with_report  # noqa: E402
from accollab.store import Store  # noqa: E402
from test_sync import G1  # noqa: E402


class CommentsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.a = Store(os.path.join(self.tmp.name, "a.db"))
        self.b = Store(os.path.join(self.tmp.name, "b.db"))

    def tearDown(self):
        self.a.close()
        self.b.close()
        self.tmp.cleanup()

    def test_local_add_reply_resolve(self):
        cid, op = comments.add_local(self.a, G1, "anna", "proverit vysotu", ["boris"])
        self.assertEqual(op["kind"], "comment")
        self.assertEqual(op["op"], "comment.add")
        self.assertEqual(len(comments.list_for_element(self.a, G1)), 1)
        op2 = comments.reply_local(self.a, cid, "boris", "proveril, ok")
        self.assertEqual(op2["op"], "comment.reply")
        self.assertEqual(len(comments.list_open(self.a)), 1)
        op3 = comments.resolve_local(self.a, cid, "anna")
        self.assertEqual(op3["op"], "comment.resolve")
        self.assertEqual(comments.list_open(self.a), [])

    def test_remote_roundtrip(self):
        cid, op_add = comments.add_local(self.a, G1, "anna", "vopros")
        self.assertEqual(comments.apply_remote(self.b, op_add), "COMMENT-APPLIED")
        self.assertEqual(comments.apply_remote(self.b, op_add), "COMMENT-DUP")
        got = comments.list_for_element(self.b, G1)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["text"], "vopros")
        op_reply = comments.reply_local(self.a, cid, "boris", "otvet")
        self.assertEqual(comments.apply_remote(self.b, op_reply), "COMMENT-REPLIED")
        self.assertEqual(comments.apply_remote(self.b, op_reply), "COMMENT-DUP")
        op_res = comments.resolve_local(self.a, cid, "anna")
        self.assertEqual(comments.apply_remote(self.b, op_res), "COMMENT-RESOLVED")
        self.assertEqual(comments.list_open(self.b), [])

    def test_via_applier(self):
        _, op = comments.add_local(self.a, G1, "anna", "cherez applier")
        rep = apply_with_report(None, self.b, op)
        self.assertEqual(rep["status"], "COMMENT-APPLIED")
        row = self.b.get_operation(op["change_id"])
        self.assertEqual(row["applied"], 1)

    def test_bad_inputs(self):
        self.assertEqual(comments.apply_remote(self.b, {"op": "comment.add",
                                                        "after_json": "ne-json"}),
                         "SKIP-comment-badjson")
        self.assertEqual(comments.apply_remote(self.b, {"op": "comment.add",
                                                        "after_json": "{}"}),
                         "SKIP-comment-noid")
        with self.assertRaises(ValueError):
            comments.add_local(self.a, G1, "anna", "   ")
        with self.assertRaises(KeyError):
            comments.reply_local(self.a, "cm-net", "anna", "x")
        with self.assertRaises(KeyError):
            comments.resolve_local(self.a, "cm-net", "anna")


if __name__ == "__main__":
    unittest.main()
