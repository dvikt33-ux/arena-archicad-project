"""Тесты Watcher: снимок → мутация → diff → операция. Только stdlib."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from accollab.connector import ArchicadConnection  # noqa: E402
from accollab.store import Store  # noqa: E402
from accollab.watcher import Watcher, diff_items  # noqa: E402
from mock_archicad import Handler, start_mock  # noqa: E402


class WatcherTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server, cls.port = start_mock()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        Handler.mutations = {}
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(os.path.join(self.tmp.name, "w.db"))
        self.conn = ArchicadConnection(self.port)
        self.w = Watcher(self.conn, self.store, "p1", "tester")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_diff_pure(self):
        old = {"a": {"checksum": "1"}, "b": {"checksum": "2"}}
        new = {"b": {"checksum": "X"}, "c": {"checksum": "3"}}
        d = diff_items(old, new)
        self.assertEqual((d["created"], d["deleted"], d["modified"]),
                         (["c"], ["a"], ["b"]))

    def test_first_poll_is_baseline(self):
        rep = self.w.poll_and_record()
        self.assertTrue(rep.get("baseline"))
        self.assertEqual(rep["ops"], [])
        self.assertEqual(rep["count"], 3)

    def test_mutation_yields_one_modify(self):
        self.w.poll_and_record()  # база
        victim = self.conn.get_all_guids()[0]
        Handler.mutations = {victim: {"x": 999.0}}
        rep = self.w.poll_and_record()
        self.assertEqual(rep["modified"], [victim])
        self.assertEqual(len(rep["ops"]), 1)
        op = self.store.get_operation(rep["ops"][0])
        self.assertEqual((op["op"], op["element_guid"]), ("modify", victim))
        self.assertIn("999.0", op["after_json"])
        self.assertNotIn("999.0", op["before_json"])
        self.assertIn(rep["ops"][0], self.store.list_outbox())

    def test_no_changes_no_ops(self):
        self.w.poll_and_record()
        rep = self.w.poll_and_record()
        self.assertEqual(rep["ops"], [])


if __name__ == "__main__":
    unittest.main()
