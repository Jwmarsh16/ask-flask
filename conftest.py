# conftest.py
# Ensure the repository root is importable as a package root during pytest runs.
# This makes `import server` work regardless of how pytest determines rootdir.

import os
import pathlib
import sys

# CHANGED: add pytest fixtures/hooks to init + reset DB schema in clean CI runners
import pytest

# CHANGED: signals "test mode" early enough to affect app import-time init
os.environ.setdefault("ASKFLASK_TESTING", "1")

ROOT = pathlib.Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))  # <-- add repo root to Python path

# CHANGED: force tests to use an isolated SQLite file DB (prevents CI "no such table"
# and avoids accidentally hitting a real DATABASE_URI like Postgres)
_TEST_DB_PATH = ROOT / "server" / "instance" / "pytest_app.db"
# CHANGED: ensure instance/ exists for CI
_TEST_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
try:
    # CHANGED: start from a clean DB each run (deterministic tests)
    _TEST_DB_PATH.unlink()
except FileNotFoundError:
    pass

# CHANGED: override any external DB config during tests
os.environ["DATABASE_URI"] = f"sqlite:///{_TEST_DB_PATH}"

_DB_READY = False  # CHANGED: one-time schema init guard


def _ensure_schema() -> None:
    """Ensure the DB schema exists for the test DB (fresh CI runners have no tables)."""
    # CHANGED: use module-level guard to avoid repeated create_all
    global _DB_READY
    if _DB_READY:
        return

    from importlib import import_module

    app_mod = import_module("server.app")
    app = app_mod.app
    from server.config import db

    with app.app_context():
        db.create_all()  # CHANGED: create tables from models for test DB

    _DB_READY = True  # CHANGED: mark schema ready for the rest of the run


def pytest_sessionstart(session) -> None:
    _ensure_schema()  # CHANGED: ensure tables exist before any tests execute (CI-safe)


@pytest.fixture(autouse=True)
def _clean_db_between_tests():
    _ensure_schema()  # CHANGED: belt-and-suspenders for environments that skip sessionstart
    from importlib import import_module

    app_mod = import_module("server.app")
    app = app_mod.app
    from server.config import db
    from server.models import Message, Session

    with app.app_context():
        # CHANGED: clear child rows first for FK safety
        db.session.query(Message).delete()
        # CHANGED: clear parent rows to keep tests isolated
        db.session.query(Session).delete()
        # CHANGED: persist cleanup so each test starts from a known-empty DB
        db.session.commit()

    yield
