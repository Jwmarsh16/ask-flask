# server/tests/test_chat_persistence.py
# Purpose: Verify DB persistence and prompt context assembly without touching internal code.
# Strategy:
# - Use only public endpoints (/api/sessions, /api/chat, /api/chat/stream).
# - Monkeypatch the OpenAI service entry points (openai_service.complete / .stream)
#   to be deterministic and to capture the 'messages' we send to the model.
# - Assert that:
#     • Non-stream & stream both persist user+assistant messages to the session.
#     • The prompt assembly honors CHAT_CONTEXT_MAX_TURNS (turn-count window).
#
# Notes:
# - These tests do NOT import or mutate models directly; they fetch messages via
#   GET /api/sessions/:id as defined in the API contract.
# - For context tests, we set CHAT_CONTEXT_MAX_TURNS with monkeypatch.setenv.
# - Assumes: app exposes `openai_service` with functions `complete(model, messages)`
#   and `stream(model, messages)` that the routes call.

from importlib import import_module
import types


def _create_session(client):
    """Create a fresh session via API and return its id."""
    r = client.post("/api/sessions", json={})
    assert r.status_code == 200
    data = r.get_json()
    assert "id" in data
    return data["id"]


def _get_session_messages(client, session_id):
    """Fetch messages for a session via API and return the list (ascending by created_at)."""
    r = client.get(f"/api/sessions/{session_id}")
    assert r.status_code == 200
    data = r.get_json()
    msgs = data.get("messages", [])
    assert isinstance(msgs, list)
    return msgs


def test_persists_user_and_assistant_non_stream(monkeypatch):
    app_mod = import_module("server.app")
    app = app_mod.app

    # Deterministic non-stream stub that returns fixed text and captures messages.
    captured = {"messages": None}

    def fake_complete(model, messages):
        captured["messages"] = messages  # capture assembled prompt for inspection
        return "MOCK-REPLY"

    monkeypatch.setattr(app_mod.openai_service, "complete", fake_complete)

    with app.test_client() as c:
        session_id = _create_session(c)

        # Call chat with session_id → should append user + assistant after success
        r = c.post("/api/chat", json={"message": "Hello non-stream", "model": "gpt-4", "session_id": session_id})
        assert r.status_code == 200
        body = r.get_json()
        assert body.get("reply") == "MOCK-REPLY"

        # Verify persistence via Sessions API
        msgs = _get_session_messages(c, session_id)
        # Expect: [ user, assistant ]
        assert len(msgs) == 2
        assert msgs[0]["role"] == "user" and msgs[0]["content"] == "Hello non-stream"
        assert msgs[1]["role"] == "assistant" and msgs[1]["content"] == "MOCK-REPLY"

        # Sanity: server assembled a prompt with system + prior turns + current user
        assert isinstance(captured["messages"], list) and len(captured["messages"]) >= 2
        assert captured["messages"][0]["role"] in ("system", "developer")  # system lead is expected


def test_persists_user_and_assistant_stream(monkeypatch):
    app_mod = import_module("server.app")
    app = app_mod.app

    # Deterministic streaming stub: yields two tokens "Hi" and "!" then stops.
    def fake_stream(model, messages):
        # Emulate an iterator of chunks consistent with route logic (just tokens as strings)
        def _gen():
            yield "Hi"
            yield "!"
        return _gen()

    monkeypatch.setattr(app_mod.openai_service, "stream", fake_stream)

    with app.test_client() as c:
        session_id = _create_session(c)

        r = c.post("/api/chat/stream", json={"message": "Hello stream", "model": "gpt-4", "session_id": session_id})
        # SSE happy path returns 200; body contains event-stream frames (not parsed here).
        assert r.status_code == 200
        payload = r.data.decode("utf-8")
        assert "text/event-stream" in r.headers.get("Content-Type", "")
        assert "data:" in payload and '"done": true' in payload

        # After stream completes, assistant content should be the concatenated tokens "Hi!"
        msgs = _get_session_messages(c, session_id)
        assert len(msgs) == 2
        assert msgs[0]["role"] == "user" and msgs[0]["content"] == "Hello stream"
        assert msgs[1]["role"] == "assistant" and msgs[1]["content"] == "Hi!"


def test_context_window_respects_turn_count(monkeypatch):
    app_mod = import_module("server.app")
    app = app_mod.app

    # We'll build 4 prior user/assistant exchanges, then set CHAT_CONTEXT_MAX_TURNS=2.
    # The final call should include only the last 2 prior exchanges in the prompt.
    def deterministic_reply(model, messages):
        # Just return a constant. We also stash the messages for asserts using outer scope var.
        captured["messages"] = messages
        return "CTX-OK"

    captured = {"messages": None}
    with app.test_client() as c:
        # Create session and pre-fill with 4 exchanges via the public /api/chat endpoint.
        session_id = _create_session(c)

        # Use a simple stub for these seeds.
        monkeypatch.setattr(app_mod.openai_service, "complete", lambda model, messages: "seed-reply")

        for i in range(4):
            r = c.post(
                "/api/chat",
                json={"message": f"seed-{i}", "model": "gpt-3.5-turbo", "session_id": session_id},
            )
            assert r.status_code == 200

        # Now switch to our capturing stub and set the knob to 2 turns.
        monkeypatch.setattr(app_mod.openai_service, "complete", deterministic_reply)
        monkeypatch.setenv("CHAT_CONTEXT_MAX_TURNS", "2")

        r = c.post(
            "/api/chat",
            json={"message": "final", "model": "gpt-4", "session_id": session_id},
        )
        assert r.status_code == 200
        assert r.get_json().get("reply") == "CTX-OK"

        # Validate the assembled OpenAI messages list:
        msgs = captured["messages"]
        assert isinstance(msgs, list) and len(msgs) >= 1

        # Expect structure: [system, (user,assistant) x N (N<=2), current user]
        roles = [m["role"] for m in msgs]
        # System or developer first
        assert roles[0] in ("system", "developer")
        # Last should be the current user
        assert roles[-1] == "user" and msgs[-1]["content"] == "final"

        # Extract just the alternating prior pairs (skip first system and last current user)
        prior = msgs[1:-1]
        # Should be exactly 2 exchanges -> 4 messages
        assert len(prior) == 4
        # They should be the LAST two from our 4 seeds: seed-2 and seed-3 pairs
        expected_prior_users = ["seed-2", "seed-3"]
        actual_prior_users = [prior[0]["content"], prior[2]["content"]]
        assert actual_prior_users == expected_prior_users


def test_context_window_zero_includes_no_prior(monkeypatch):
    app_mod = import_module("server.app")
    app = app_mod.app

    # Build 2 prior exchanges, then set the knob to 0; only system + current user should be sent.
    captured = {"messages": None}

    def deterministic_reply(model, messages):
        captured["messages"] = messages
        return "CTX-EMPTY"

    with app.test_client() as c:
        session_id = _create_session(c)

        # Seed 2 exchanges
        monkeypatch.setattr(app_mod.openai_service, "complete", lambda model, messages: "seed")
        for i in range(2):
            r = c.post(
                "/api/chat",
                json={"message": f"seed-{i}", "model": "gpt-3.5-turbo", "session_id": session_id},
            )
            assert r.status_code == 200

        # Now assert with knob=0
        monkeypatch.setattr(app_mod.openai_service, "complete", deterministic_reply)
        monkeypatch.setenv("CHAT_CONTEXT_MAX_TURNS", "0")

        r = c.post(
            "/api/chat",
            json={"message": "final-0", "model": "gpt-4", "session_id": session_id},
        )
        assert r.status_code == 200

        msgs = captured["messages"]
        assert isinstance(msgs, list) and len(msgs) >= 2
        # Expect only [system, user(final-0)] — i.e., no prior turns were included
        assert msgs[0]["role"] in ("system", "developer")
        assert msgs[-1]["role"] == "user" and msgs[-1]["content"] == "final-0"
        # Everything between should be empty if knob=0
        assert msgs[1:-1] == []
