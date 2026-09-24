"""Тесты BIM-контроля: дубли ID, пустые ID, материалы, чисто."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from accollab import bim_checks  # noqa: E402


def item(el_id, material=True):
    inner = {"buildingMaterialId": {"guid": "m1"}} if material else {}
    return {"type": "Beam", "details": {"id": el_id, "details": inner}}


class BimTest(unittest.TestCase):
    def test_duplicates(self):
        items = {"g1": item("БЛК-1"), "g2": item("БЛК-1"), "g3": item("БЛК-2")}
        rep = bim_checks.run_all(items)
        self.assertEqual(rep["counts"], {"DUP_ID": 1})
        self.assertEqual(rep["issues"][0]["id"], "БЛК-1")
        self.assertEqual(len(rep["issues"][0]["guids"]), 2)

    def test_empty(self):
        items = {"g1": item(""), "g2": item("БЛК-2")}
        rep = bim_checks.run_all(items)
        self.assertEqual(rep["counts"], {"EMPTY_ID": 1})

    def test_missing_material(self):
        items = {"g1": item("БЛК-1", material=False), "g2": item("БЛК-2")}
        rep = bim_checks.run_all(items)
        self.assertEqual(rep["counts"], {"NO_MATERIAL": 1})
        self.assertEqual(rep["issues"][0]["guid"], "g1")

    def test_clean(self):
        items = {"g1": item("БЛК-1"), "g2": item("БЛК-2")}
        rep = bim_checks.run_all(items)
        self.assertEqual(rep["issues"], [])
        self.assertEqual(rep["counts"], {})


    def test_rules_filter(self):
        items = {"g1": item("БЛК-1"), "g2": item("БЛК-1"), "g3": item("")}
        rep = bim_checks.run_all(items, rules="DUP_ID")
        self.assertEqual(rep["counts"], {"DUP_ID": 1})
        rep = bim_checks.run_all(items, rules="empty_id, NO_MATERIAL")
        self.assertEqual(rep["counts"], {"EMPTY_ID": 1})
        rep = bim_checks.run_all(items, rules="all")
        self.assertEqual(rep["counts"], {"DUP_ID": 1, "EMPTY_ID": 1})


if __name__ == "__main__":
    unittest.main()
