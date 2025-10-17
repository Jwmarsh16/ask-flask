# conftest.py  (at repo root)
# Ensure the repository root is importable as a package root during pytest runs.
# This makes `import server` work regardless of how pytest determines rootdir.
import sys, pathlib
ROOT = pathlib.Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))  # <-- add repo root to Python path
