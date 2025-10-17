# server/tests/test_sessions_api.py
import json
import uuid
import time

import pytest

# NOTE: We import the global Flask app as configured by the project.
# This keeps parity with production wiring (logging, headers, limiter, etc.).
from server.app import app  # <-- USE EXISTING APP FACTORY/WIRING


@pytest.fixture(scope="module")
def client():
    """
    Provide a Flask test client against the real app instance.
    We rely on the project's default fallback to SQLite for tests.
    """
    app.config["TESTING"] = True  # <-- enable Flask testing flags
    with app.test_client() as c:
        yield c


# ---------------------------
# Helpers
# ---------------------------

def _create_session(client, title="PyTest Session"):
    """Create a session via API and return its JSON payload."""
    resp = client.post("/api/sessions", data=json.dumps({"title": title}), content_type="application/json")
    assert resp.status_code == 200, f"Create session failed: {resp.data}"
    _assert_common_headers(resp)  # <-- verify security/request-id headers
    body = resp.get_json()
    assert isinstance(body, dict) and "id" in body and body["id"], "Session id missing"
    return body


def _append_message(client, session_id, role="user", content="hello"):
    """Append a message to a session and return created message JSON."""
    resp = client.post(
        f"/api/sessions/{session_id}/messages",
        data=json.dumps({"role": role, "content": content}),
        content_type="application/json",
    )
    assert resp.status_code == 201, f"Append message failed: {resp.data}"
    _assert_common_headers(resp)  # <-- verify security/request-id headers
    body = resp.get_json()
    assert isinstance(body, dict) and body.get("role") == role and body.get("content") == content
    return body


def _get_session(client, session_id):
    """Fetch a session by id."""
    resp = client.get(f"/api/sessions/{session_id}")
    assert resp.status_code == 200, f"Get session failed: {resp.data}"
    _assert_common_headers(resp)  # <-- verify security/request-id headers
    return resp.get_json()


def _delete_session(client, session_id):
    """Delete a session by id."""
    resp = client.delete(f"/api/sessions/{session_id}")
    assert resp.status_code == 204, f"Delete session failed: {resp.data}"
    _assert_common_headers(resp)  # <-- verify security/request-id headers


def _export_session(client, session_id, fmt):
    """Download a session export in the requested format."""
    resp = client.get(f"/api/sessions/{session_id}/export?format={fmt}")
    assert resp.status_code == 200, f"Export ({fmt}) failed: {resp.data}"
    _assert_common_headers(resp)  # <-- verify security/request-id headers
    cd = resp.headers.get("Content-Disposition", "")
    assert "attachment" in cd and (".json" in cd or ".md" in cd)
    assert resp.data, "Export body should not be empty"
    return resp


def _rename_session(client, session_id, title):  # <-- ADDED: helper for PATCH rename
    """Rename a session via PATCH and return its JSON payload."""
    resp = client.patch(
        f"/api/sessions/{session_id}",
        data=json.dumps({"title": title}),
        content_type="application/json",
    )
    assert resp.status_code == 200, f"Rename session failed: {resp.data}"  # <-- ADDED
    _assert_common_headers(resp)  # <-- ADDED
    return resp.get_json()


def _assert_common_headers(resp):
    """Common headers enforced by security/observability layers."""
    assert resp.headers.get("X-Request-ID"), "Missing X-Request-ID header"  # <-- request correlation
    # Security headers (subset, presence check)
    assert resp.headers.get("X-Frame-Options") == "DENY"
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("Referrer-Policy") == "no-referrer"
    assert "default-src 'self'" in (resp.headers.get("Content-Security-Policy") or "")


# ---------------------------
# Tests
# ---------------------------

def test_create_and_list_sessions(client):
    created = _create_session(client)
    created_id = created["id"]

    # List should include the created session with last_activity
    resp = client.get("/api/sessions")
    assert resp.status_code == 200
    _assert_common_headers(resp)  # <-- verify security/request-id headers
    items = resp.get_json()
    assert isinstance(items, list)
    found = next((s for s in items if s["id"] == created_id), None)
    assert found is not None, "Created session not in list"
    assert "last_activity" in found, "last_activity missing in list payload"

    # Cleanup
    _delete_session(client, created_id)


def test_get_session_and_messages_order(client):
    s = _create_session(client)
    sid = s["id"]

    # Append two messages in order; tiny sleep to ensure created_at ordering if needed
    _append_message(client, sid, "user", "first")
    time.sleep(0.01)  # <-- ensure distinct timestamps under fast clocks
    _append_message(client, sid, "assistant", "second")

    data = _get_session(client, sid)
    msgs = data.get("messages", [])
    assert len(msgs) >= 2
    # Expect ascending by created_at — first message content should be "first"
    assert msgs[0]["content"] == "first"
    assert msgs[1]["content"] == "second"

    _delete_session(client, sid)


def test_export_json_and_markdown(client):
    s = _create_session(client)
    sid = s["id"]
    _append_message(client, sid, "user", "hello json/md")

    # JSON export
    rjson = _export_session(client, sid, "json")
    assert rjson.mimetype in ("application/json", "application/octet-stream")  # some servers set octet-stream for downloads

    # Markdown export
    rmd = _export_session(client, sid, "md")
    # Many servers use octet-stream for downloads; accept either
    assert rmd.mimetype in ("text/markdown", "text/plain", "application/octet-stream")

    _delete_session(client, sid)


def test_delete_cascades_messages(client):
    s = _create_session(client)
    sid = s["id"]
    _append_message(client, sid, "user", "to be deleted")
    _delete_session(client, sid)

    # Subsequent GET should 404
    resp = client.get(f"/api/sessions/{sid}")
    assert resp.status_code == 404
    _assert_common_headers(resp)  # <-- verify security/request-id headers
    body = resp.get_json()
    assert isinstance(body, dict) and body.get("error"), "Unified error body expected on 404"
    assert body.get("code") == 404


def test_404_invalid_session_id(client):
    fake = str(uuid.uuid4())
    resp = client.get(f"/api/sessions/{fake}")
    assert resp.status_code == 404
    _assert_common_headers(resp)  # <-- verify security/request-id headers
    body = resp.get_json()
    assert isinstance(body, dict) and body.get("error")
    assert body.get("code") == 404


def test_400_invalid_append_payload(client):
    s = _create_session(client)
    sid = s["id"]

    # Invalid role
    resp = client.post(
        f"/api/sessions/{sid}/messages",
        data=json.dumps({"role": "banana", "content": "nope"}),
        content_type="application/json",
    )
    assert resp.status_code == 400
    _assert_common_headers(resp)  # <-- verify security/request-id headers
    body = resp.get_json()
    assert isinstance(body, dict) and body.get("error")
    assert body.get("code") == 400

    # Missing content
    resp2 = client.post(
        f"/api/sessions/{sid}/messages",
        data=json.dumps({"role": "user"}),
        content_type="application/json",
    )
    assert resp2.status_code == 400
    _assert_common_headers(resp2)  # <-- verify security/request-id headers
    body2 = resp2.get_json()
    assert isinstance(body2, dict) and body2.get("error")
    assert body2.get("code") == 400

    _delete_session(client, sid)


# ---------------------------
# NEW: PATCH rename tests
# ---------------------------

def test_patch_rename_happy_path(client):  # <-- ADDED
    s = _create_session(client, title="Old Title")
    sid = s["id"]

    new_title = "  New Title  "  # leading/trailing spaces should be trimmed  # <-- ADDED
    body = _rename_session(client, sid, new_title)
    assert body["title"] == "New Title"  # trimmed result                      # <-- ADDED

    # Fetch to confirm persistence                                               # <-- ADDED
    fetched = _get_session(client, sid)
    assert fetched["title"] == "New Title"

    _delete_session(client, sid)


def test_patch_rename_validation_errors(client):  # <-- ADDED
    s = _create_session(client)
    sid = s["id"]

    # Empty title                                                                # <-- ADDED
    resp1 = client.patch(
        f"/api/sessions/{sid}",
        data=json.dumps({"title": ""}),
        content_type="application/json",
    )
    assert resp1.status_code == 400
    _assert_common_headers(resp1)

    # Whitespace-only title                                                      # <-- ADDED
    resp2 = client.patch(
        f"/api/sessions/{sid}",
        data=json.dumps({"title": "   "}),
        content_type="application/json",
    )
    assert resp2.status_code == 400
    _assert_common_headers(resp2)

    # Overlong title (>200 chars)                                                # <-- ADDED
    resp3 = client.patch(
        f"/api/sessions/{sid}",
        data=json.dumps({"title": "x" * 201}),
        content_type="application/json",
    )
    assert resp3.status_code == 400
    _assert_common_headers(resp3)

    _delete_session(client, sid)


def test_patch_rename_not_found(client):  # <-- ADDED
    fake = str(uuid.uuid4())
    resp = client.patch(
        f"/api/sessions/{fake}",
        data=json.dumps({"title": "Does Not Exist"}),
        content_type="application/json",
    )
    assert resp.status_code == 404
    _assert_common_headers(resp)
    body = resp.get_json()
    assert isinstance(body, dict) and body.get("code") == 404
