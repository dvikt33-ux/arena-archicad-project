"""Tochka vhoda dlya EXE (PyInstaller): absolyutnyy import paketa."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from accollab.daemon import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
