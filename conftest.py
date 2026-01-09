# conftest.py
# Ensure the repository root is importable as a package root during pytest runs.
# This makes `import server` work regardless of how pytest determines rootdir.

import os
import pathlib
import sys

import pytest  # CHANGED: add pytest fixture/hooks to init + reset DB schema in clean CI runners

# CHANGED: signals "test mode" early enough to affect app import-time init
os.environ.setdefault("ASKFLASK_TESTING", "1")

ROOT = pathlib.Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))  # <-- add repo root to Python path

# CHANGED: force tests to use an isolated SQLite file DB (prevents CI "no such table"
# and avoids accidentally hitting a real DATABASE_URI like Postgres)
_TEST_DB_PATH = ROOT / "server" / "instance" / "pytest_app.db"
_TEST_DB_PATH.parent.mkdir(parents=True, exist_ok=True)  # CHANGED: ensure instance/ exists for CI
try:
    _TEST_DB_PATH.unlink()  # CHANGED: start from a clean DB each run (deterministic tests)
except FileNotFoundError:
    pass

os.environ["DATABASE_URI"] = f"sqlite:///{_TEST_DB_PATH}"  # CHANGED: override any external DB config during tests

_DB_READY = False  # CHANGED: one-time schema init guard


def _ensure_schema() -> None:
    """Ensure the DB schema exists for the test DB (fresh CI runners have no tables)."""
    global _DB_READY  # CHANGED: use module-level guard to avoid repeated create_all
    if _DB_READY:
        return

    from importlib import import_module

    app_mod = import_module("server.app")
    app = app_mod.app
    from server.config import db

    with app.app_context():
        db.create_all()  # CHANGED: create tables from models for test DB

    _DB_READY = True  # CHANGED: mark schema ready for the rest of the run


def pytest_sessionstart(session):
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
        db.session.query(Message).delete()  # CHANGED: clear child rows first for FK safety
        db.session.query(Session).delete()  # CHANGED: clear parent rows to keep tests isolated
        db.session.commit()  # CHANGED: persist cleanup so each test starts from a known-empty DB

    yield
