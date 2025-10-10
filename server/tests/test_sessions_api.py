# server/tests/test_sessions_api.py
import json

# Import app in a way that works both locally and in CI
try:
    from server.app import app  # package mode
except Exception:
    from app import app  # top-level mode


def _json(resp):
    return json.loads(resp.data.decode("utf-8"))


def test_sessions_crud_and_export():
    with app.test_client() as c:
        # Create a session
        r = c.post("/api/sessions", json={"title": "My Session"})
        assert r.status_code == 200
        s = _json(r)
        sid = s["id"]
        assert s["title"] == "My Session"

        # List sessions includes our new one
        r = c.get("/api/sessions")
        assert r.status_code == 200
        rows = _json(r)
        assert any(row["id"] == sid for row in rows)

        # Append a user message
        r = c.post(f"/api/sessions/{sid}/messages", json={"role": "user", "content": "Hello"})
        assert r.status_code == 201
        m = _json(r)
        assert m["role"] == "user"
        assert m["content"] == "Hello"

        # Fetch session detail
        r = c.get(f"/api/sessions/{sid}")
        assert r.status_code == 200
        detail = _json(r)
        assert detail["id"] == sid
        assert len(detail["messages"]) >= 1

        # Export JSON
        r = c.get(f"/api/sessions/{sid}/export?format=json")
        assert r.status_code == 200
        assert r.headers["Content-Type"].startswith("application/json")
        assert "attachment; filename=" in r.headers.get("Content-Disposition", "")

        # Export Markdown
        r = c.get(f"/api/sessions/{sid}/export?format=md")
        assert r.status_code == 200
        assert r.headers["Content-Type"].startswith("text/markdown")
        assert "attachment; filename=" in r.headers.get("Content-Disposition", "")

        # Delete the session
        r = c.delete(f"/api/sessions/{sid}")
        assert r.status_code == 204

        # Subsequent fetch should 404
        r = c.get(f"/api/sessions/{sid}")
        assert r.status_code == 404
