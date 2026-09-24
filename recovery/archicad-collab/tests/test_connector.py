"""Тесты коннектора против фейкового Archicad. Только stdlib: python -m unittest."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from accollab.connector import ArchicadConnection, ArchicadError  # noqa: E402
from accollab.store import Store, element_checksum  # noqa: E402
from mock_archicad import Handler, start_mock  # noqa: E402


class ConnectorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server, cls.port = start_mock()
        cls.conn = ArchicadConnection(cls.port)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_product_info(self):
        info = self.conn.get_product_info()
        self.assertEqual((info["version"], info["buildNumber"]), (29, 3000))

    def test_all_guids(self):
        self.assertEqual(len(self.conn.get_all_guids()), 3)

    def test_types(self):
        types = self.conn.get_types_of_elements(self.conn.get_all_guids())
        self.assertEqual(set(types.values()), {"Beam"})

    def test_tapir_version(self):
        self.assertEqual(self.conn.get_tapir_version(), "1.5.9")

    def test_project_info(self):
        self.assertEqual(self.conn.get_project_info()["projectName"], "mock")

    def test_details(self):
        dets = self.conn.get_details(self.conn.get_all_guids()[:2])
        self.assertEqual(len(dets), 2)
        self.assertEqual(dets[0]["type"], "Beam")

    def test_highlight(self):
        res = self.conn.highlight(self.conn.get_all_guids()[:1])
        self.assertTrue(res.get("success"))

    def test_fit_in_window(self):
        Handler.calls.clear()
        res = self.conn.fit_in_window(self.conn.get_all_guids()[:1])
        self.assertTrue(res.get("success"))
        self.assertEqual(Handler.calls[-1][0], "FitInWindow")

    def test_show_alert(self):
        Handler.calls.clear()
        Handler.alert_button = 2
        try:
            btn = self.conn.show_alert("t", "m", "b1", "b2", "b3")
        finally:
            Handler.alert_button = 1
        self.assertEqual(btn, 2)
        self.assertEqual(Handler.calls[-1][0], "ShowAlert")

    def test_unknown_command_raises_2002(self):
        with self.assertRaises(ArchicadError) as ctx:
            self.conn.official("NoSuchCommand")
        self.assertEqual(ctx.exception.code, 2002)

    def test_ping(self):
        ping = self.conn.ping()
        self.assertEqual((ping["tapir"], ping["elements"]), ("1.5.9", 3))


class StoreTest(unittest.TestCase):
    def test_schema_and_idempotency(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(os.path.join(tmp, "t.db"))
            store.upsert_element("g1", "Beam", element_checksum({"a": 1}), updated_at="t")
            self.assertEqual(store.element_count(), 1)
            op = {"change_id": "c1", "project_id": "p", "element_guid": "g1",
                  "author": "u", "wall_time": "t", "op": "modify"}
            self.assertTrue(store.insert_operation(op))
            self.assertFalse(store.insert_operation(op))  # дубль — no-op
            self.assertEqual(store.get_operation("c1")["op"], "modify")
            store.close()


if __name__ == "__main__":
    unittest.main()
