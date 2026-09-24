"""Тесты бэкапа: копия+сверка, ротация, чужие файлы не трогаем, ошибки."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from accollab import backup  # noqa: E402


class BackupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.src = os.path.join(self.tmp.name, "tropa.pln")
        with open(self.src, "wb") as f:
            f.write(b"PLN" * 1000)
        self.bdir = os.path.join(self.tmp.name, "bk")

    def tearDown(self):
        self.tmp.cleanup()

    def test_happy_path(self):
        rep = backup.backup_file(self.src, self.bdir, keep=5, prefix="tropa")
        self.assertTrue(os.path.exists(rep["path"]))
        self.assertEqual(rep["bytes"], 3000)
        self.assertEqual(backup.sha256_file(rep["path"]), rep["sha256"])
        self.assertEqual(rep["removed"], [])

    def test_rotation_and_collision(self):
        reps = [backup.backup_file(self.src, self.bdir, keep=2, prefix="tropa")
                for _ in range(3)]
        paths = [r["path"] for r in reps]
        self.assertEqual(len(set(paths)), 3)  # коллизии имён разрулены
        left = sorted(f for f in os.listdir(self.bdir) if f.endswith(".pln"))
        self.assertEqual(len(left), 2)  # ротация держит 2
        self.assertEqual(len(reps[-1]["removed"]), 1)

    def test_foreign_files_safe(self):
        os.makedirs(self.bdir, exist_ok=True)
        with open(os.path.join(self.bdir, "README.txt"), "w") as f:
            f.write("ne trogat")
        with open(os.path.join(self.bdir, "other-20240101.pln"), "wb") as f:
            f.write(b"x")
        for _ in range(3):
            backup.backup_file(self.src, self.bdir, keep=1, prefix="tropa")
        self.assertTrue(os.path.exists(os.path.join(self.bdir, "README.txt")))
        self.assertTrue(os.path.exists(os.path.join(self.bdir, "other-20240101.pln")))

    def test_errors(self):
        with self.assertRaises(backup.BackupError):
            backup.backup_file(os.path.join(self.tmp.name, "net.pln"), self.bdir)
        empty = os.path.join(self.tmp.name, "empty.pln")
        open(empty, "wb").close()
        with self.assertRaises(backup.BackupError):
            backup.backup_file(empty, self.bdir)


if __name__ == "__main__":
    unittest.main()
