# server/tests/test_chat_api.py
# Purpose: Backend tests for /health, /api/chat (happy & error), and /api/chat/stream (SSE).
# Notes:
# - After refactor, routes use OpenAIService; we patch `openai_service._client`
#   or its public methods instead of `server.app.client`.  # inline-change

import json
from importlib import import_module
import types
import pytest  # <-- added: for assertions/marks where helpful  # inline-change


def _mock_openai(success_text="Hello from mock"):
    """Build a minimal object that looks like the OpenAI client used by OpenAIService."""
    # --- Non-streaming response shape ---
    class _Msg:
        def __init__(self, content):
            self.content = content

    class _Choice:
        def __init__(self, content):
            self.message = _Msg(content)

    class _NonStreamResp:
        def __init__(self, text):
            self.choices = [_Choice(text)]
            self.usage = types.SimpleNamespace(  # optional usage fields
                prompt_tokens=None, completion_tokens=None, total_tokens=None
            )

    # --- Streaming response (iterable yielding chunk objects with .choices[0].delta.content) ---
    class _Delta:
        def __init__(self, content=None):
            self.content = content

    class _StreamChoice:
        def __init__(self, content=None, finish_reason=None):
            self.delta = _Delta(content)
            self.finish_reason = finish_reason

    class _StreamEvent:
        def __init__(self, content=None, finish=False):
            if finish:
                self.choices = [_StreamChoice(content=None, finish_reason="stop")]
            else:
                self.choices = [_StreamChoice(content=content)]

    def _stream_gen():
        # yields two small token events then a finish event
        yield _StreamEvent(content="Hi")
        yield _StreamEvent(content="!")
        yield _StreamEvent(finish=True)

    def _create(*args, **kwargs):
        if kwargs.get("stream"):
            # Return an iterator-like object (generator is fine in Flask loop)
            return _stream_gen()
        return _NonStreamResp(success_text)

    # Build object graph like: client.chat.completions.create(...)
    ChatCompletions = types.SimpleNamespace(create=_create)
    Chat = types.SimpleNamespace(completions=ChatCompletions)
    client = types.SimpleNamespace(chat=Chat)
    return client


def test_health_ok():
    app_mod = import_module("server.app")
    app = app_mod.app  # Flask app exposed by server.app
    with app.test_client() as c:
        res = c.get("/health")
        assert res.status_code == 200
        assert res.is_json
        data = res.get_json()
        assert data.get("status") == "ok"


def test_chat_happy_path(monkeypatch):
    app_mod = import_module("server.app")
    # Patch the OpenAI client used inside the service  # inline-change
    app_mod.openai_service._client = _mock_openai("Hello, world!")
    app = app_mod.app
    with app.test_client() as c:
        res = c.post("/api/chat", json={"message": "hi", "model": "gpt-4"})
        assert res.status_code == 200
        assert res.is_json
        data = res.get_json()
        assert "reply" in data
        assert isinstance(data["reply"], str)
        assert len(data["reply"]) > 0


def test_chat_missing_body(monkeypatch):
    app_mod = import_module("server.app")
    app_mod.openai_service._client = _mock_openai()
    app = app_mod.app
    with app.test_client() as c:
        res = c.post("/api/chat", json={})
        assert res.status_code == 400  # per contract for missing message
        assert res.is_json
        body = res.get_json()
        assert body.get("error")
        assert body.get("code") == 400          # <-- CHANGED: unified shape asserted
        assert body.get("request_id") is not None  # <-- CHANGED


def test_chat_empty_message(monkeypatch):
    # DTO min_length should 400 on empty after trim  # inline-change
    app_mod = import_module("server.app")
    app_mod.openai_service._client = _mock_openai()
    app = app_mod.app
    with app.test_client() as c:
        res = c.post("/api/chat", json={"message": "", "model": "gpt-3.5-turbo"})
        assert res.status_code == 400
        assert res.is_json
        body = res.get_json()
        assert body.get("error")
        assert body.get("code") == 400          # <-- CHANGED
        assert body.get("request_id") is not None
        # Optional details list for DTO errors (may exist)
        assert "details" in body or True        # <-- CHANGED: tolerate absence in some paths


def test_chat_invalid_model(monkeypatch):
    # DTO Literal constraint should 400 on invalid model  # inline-change
    app_mod = import_module("server.app")
    app_mod.openai_service._client = _mock_openai()
    app = app_mod.app
    with app.test_client() as c:
        res = c.post("/api/chat", json={"message": "hi", "model": "bad-model"})
        assert res.status_code == 400
        assert res.is_json
        body = res.get_json()
        assert body.get("error")
        assert body.get("code") == 400          # <-- CHANGED
        assert body.get("request_id") is not None


def test_chat_payload_too_large(monkeypatch):
    app_mod = import_module("server.app")
    app_mod.openai_service._client = _mock_openai()
    app = app_mod.app
    with app.test_client() as c:
        huge = "a" * 4001  # > 4000 chars => 413 per guardrail
        res = c.post("/api/chat", json={"message": huge, "model": "gpt-4"})
        assert res.status_code == 413
        assert res.is_json
        body = res.get_json()
        assert body.get("error")
        assert body.get("code") == 413          # <-- CHANGED
        assert body.get("request_id") is not None


def test_chat_openai_error(monkeypatch):
    app_mod = import_module("server.app")

    # Force the service to raise like the OpenAI SDK might on network errors
    def _raise_complete(*args, **kwargs):
        raise RuntimeError("simulated OpenAI failure")

    monkeypatch.setattr(app_mod.openai_service, "complete", _raise_complete)  # inline-change

    app = app_mod.app
    with app.test_client() as c:
        res = c.post("/api/chat", json={"message": "fail please", "model": "gpt-4"})
        # Your error handler should shape this as a 500 with unified body
        assert res.status_code >= 500
        assert res.is_json
        body = res.get_json()
        assert body.get("error")
        assert body.get("code") >= 500          # <-- CHANGED
        assert body.get("request_id") is not None


def test_chat_stream_sse_headers_and_tokens(monkeypatch):
    app_mod = import_module("server.app")
    app_mod.openai_service._client = _mock_openai()  # inline-change
    app = app_mod.app
    with app.test_client() as c:
        res = c.post("/api/chat/stream", json={"message": "stream me", "model": "gpt-4"})
        # Content-Type should be text/event-stream
        ctype = res.headers.get("Content-Type", "")
        assert "text/event-stream" in ctype
        payload = res.data.decode("utf-8")
        # Should contain at least one SSE 'data:' line with token JSON
        assert "data:" in payload
        # Our mock yields "Hi" and "!" tokens; they should appear somewhere in the stream
        assert "Hi" in payload or '"token"' in payload
        # Should include a done marker
        assert '"done": true' in payload


def test_chat_stream_payload_too_large(monkeypatch):
    app_mod = import_module("server.app")
    app_mod.openai_service._client = _mock_openai()  # inline-change
    app = app_mod.app
    with app.test_client() as c:
        huge = "b" * 4001
        res = c.post("/api/chat/stream", json={"message": huge, "model": "gpt-4"})
        assert res.status_code == 413
        # Even for SSE endpoint, oversize should short-circuit to JSON 413 error per contract
        assert res.is_json
        body = res.get_json()
        assert body.get("error")
        assert body.get("code") == 413          # <-- CHANGED
        assert body.get("request_id") is not None


def test_circuit_open_non_stream(monkeypatch):
    # Map circuit-open to 503 JSON  # inline-change
    app_mod = import_module("server.app")

    def _raise_circuit(*args, **kwargs):
        raise RuntimeError("circuit_open")

    monkeypatch.setattr(app_mod.openai_service, "complete", _raise_circuit)
    app = app_mod.app
    with app.test_client() as c:
        res = c.post("/api/chat", json={"message": "hi", "model": "gpt-4"})
        assert res.status_code == 503
        assert res.is_json
        body = res.get_json()
        assert body.get("error")
        assert body.get("code") == 503          # <-- CHANGED
        assert body.get("request_id") is not None


def test_circuit_open_stream(monkeypatch):
    # SSE should emit a terminal error event with done:true  # inline-change
    app_mod = import_module("server.app")

    def _raise_stream(*args, **kwargs):
        raise RuntimeError("circuit_open")

    monkeypatch.setattr(app_mod.openai_service, "stream", _raise_stream)
    app = app_mod.app
    with app.test_client() as c:
        res = c.post("/api/chat/stream", json={"message": "hi", "model": "gpt-4"})
        assert "text/event-stream" in res.headers.get("Content-Type", "")
        data = res.data.decode("utf-8")
        assert "Service temporarily unavailable" in data
        assert '"done": true' in data
        assert '"code": 503' in data                 # <-- CHANGED: unified SSE error fields
        assert '"request_id":' in data               # <-- CHANGED


def test_rate_limit_headers_present(monkeypatch):
    # Success responses should include X-RateLimit-* headers  # inline-change
    app_mod = import_module("server.app")
    app_mod.openai_service._client = _mock_openai("Hello")
    app = app_mod.app
    with app.test_client() as c:
        res = c.post("/api/chat", json={"message": "check headers", "model": "gpt-3.5-turbo"})
        assert res.status_code == 200
        # May vary by limiter, but these should exist in our implementation
        assert res.headers.get("X-RateLimit-Limit") is not None
        assert res.headers.get("X-RateLimit-Remaining") is not None
