"""Тесты связки Watcher→Store→Transfer→Applier. Только stdlib."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from accollab.applier import (  # noqa: E402
    ConflictError, UnsupportedOpError, apply_operation, compute_move_vector)
from accollab.store import Store  # noqa: E402
from accollab.transfer import export_envelope, import_envelope  # noqa: E402
from accollab.watcher import Watcher  # noqa: E402

G1 = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
G2 = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


def beam_detail(x, bid):
    return {"type": "Beam", "id": bid,
            "details": {"begCoordinate": {"x": x, "y": 0.0},
                        "endCoordinate": {"x": x + 4.0, "y": 0.0},
                        "zCoordinate": 3.0}}


class FakeConn:
    """Минимальная поверхность коннектора + запись вызовов MoveElements."""

    def __init__(self, coords):
        self.coords = dict(coords)  # guid -> x
        self.moves = []
        self.highlights = []
        self.pln = {"projectPath": "C:\\mock\\tropa.pln", "projectName": "tropa",
                    "isUntitled": False, "isTeamwork": False}

    def get_project_info(self):
        return dict(self.pln)

    def get_all_guids(self):
        return list(self.coords)

    def get_types_of_elements(self, guids):
        return {g: "Beam" for g in guids}

    def get_details(self, guids):
        return [beam_detail(self.coords[g], f"БЛК - {g[0]}") for g in guids
                if g in self.coords]

    def tapir(self, name, params=None):
        assert name == "MoveElements"
        for item in params["elementsWithMoveVectors"]:
            g = item["elementId"]["guid"]
            self.coords[g] += item["moveVector"]["x"]  # mock: двигаем по x
            self.moves.append((g, dict(item["moveVector"])))
        return {"executionResults": [{"success": True}]}

    def highlight(self, guids, rgb=(77, 163, 255)):
        self.highlights.append((list(guids), rgb))
        return {"success": True}


class SyncTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store_a = Store(os.path.join(self.tmp.name, "a.db"))
        self.store_b = Store(os.path.join(self.tmp.name, "b.db"))

    def tearDown(self):
        self.store_a.close()
        self.store_b.close()
        self.tmp.cleanup()

    def test_vector_math(self):
        v = compute_move_vector(beam_detail(10.0, "x"), beam_detail(10.5, "x"))
        self.assertEqual(v, {"x": 0.5, "y": 0.0, "z": 0.0})
        self.assertIsNone(compute_move_vector({}, {}))

    def test_full_loop_record_transfer_apply(self):
        # Машина A: baseline, сдвиг, запись операции
        conn_a = FakeConn({G1: 100.0, G2: 200.0})
        w = Watcher(conn_a, self.store_a, "p1", "alice")
        self.assertTrue(w.poll_and_record().get("baseline"))
        conn_a.coords[G1] = 100.5  # ручной сдвиг
        rep = w.poll_and_record()
        self.assertEqual(rep["modified"], [G1])
        self.assertEqual(len(rep["ops"]), 1)
        # Перенос файлом A -> B
        env = export_envelope(self.store_a, "p1", "alice")
        self.assertEqual(len(env["ops"]), 1)
        self.assertEqual(import_envelope(self.store_b, env), 1)
        self.assertEqual(import_envelope(self.store_b, env), 0)  # идемпотентность
        # Машина B: применение (состояние B = исходное)
        conn_b = FakeConn({G1: 100.0, G2: 200.0})
        op = self.store_b.get_operation(rep["ops"][0])
        res = apply_operation(conn_b, self.store_b, op)
        self.assertEqual(res["vector"], {"x": 0.5, "y": 0.0, "z": 0.0})
        self.assertEqual(conn_b.coords[G1], 100.5)
        self.assertEqual(self.store_b.get_operation(rep["ops"][0])["applied"], 1)

    def test_conflict_on_base_mismatch(self):
        conn_a = FakeConn({G1: 100.0})
        w = Watcher(conn_a, self.store_a, "p1", "alice")
        w.poll_and_record()
        conn_a.coords[G1] = 100.5
        rep = w.poll_and_record()
        env = export_envelope(self.store_a, "p1", "alice")
        import_envelope(self.store_b, env)
        conn_b = FakeConn({G1: 101.0})  # B уже отличается — конфликт
        with self.assertRaises(ConflictError):
            apply_operation(conn_b, self.store_b,
                            self.store_b.get_operation(rep["ops"][0]))
        self.assertEqual(conn_b.moves, [])  # ничего не тронули

    def test_conflict_on_missing_element(self):
        conn_a = FakeConn({G1: 100.0})
        w = Watcher(conn_a, self.store_a, "p1", "alice")
        w.poll_and_record()
        conn_a.coords[G1] = 100.5
        rep = w.poll_and_record()
        env = export_envelope(self.store_a, "p1", "alice")
        import_envelope(self.store_b, env)
        conn_b = FakeConn({})  # элемента нет
        with self.assertRaises(ConflictError):
            apply_operation(conn_b, self.store_b,
                            self.store_b.get_operation(rep["ops"][0]))

    def test_unsupported_op(self):
        conn_b = FakeConn({G1: 100.0})
        op = {"change_id": "c", "project_id": "p", "element_guid": G1,
              "author": "a", "wall_time": "t", "op": "create",
              "before_json": "{}", "after_json": "{}"}
        with self.assertRaises(UnsupportedOpError):
            apply_operation(conn_b, self.store_b, op)


if __name__ == "__main__":
    unittest.main()
