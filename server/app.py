# server/app.py
# Flask serves ../client/dist and exposes /api routes

import os
import logging  # structured logging uses app.logger
from openai import OpenAI
from flask import (
    request,
    jsonify,
    render_template,  # SPA fallback
    current_app,      # proper logger access
    g,                # attach request_id and timing
    Response,
    stream_with_context,
)
from dotenv import load_dotenv
from pydantic import ValidationError  # handle DTO validation errors
from werkzeug.exceptions import RequestEntityTooLarge  # <-- CHANGED: use HTTPException for 413 so global handler shapes JSON

# ---------------------- Import strategy (works in BOTH launch modes) ----------------------
# If launched with:  gunicorn --chdir server app:app
#   -> this module is loaded as a *top-level* module (no package), so use absolute imports.
# If launched with:  gunicorn server.app:app
#   -> this module is loaded as part of the 'server' package, so use relative imports.
if __package__ in (None, ""):  # <-- CHANGED: mode-aware imports for top-level launch
    from config import app  # load Flask app instance  # inline-change: absolute import in top-level mode
    from observability import (  # JSON logging & middleware  # inline-change: absolute import
        init_logging,
        register_request_id,
        register_latency_logging,
        register_error_handlers,
    )
    from security import register_security_headers               # inline-change: absolute import
    from ratelimit import init_rate_limiter                      # inline-change: absolute import
    from schemas import (                                        # <-- CHANGED: import new DTOs
        ChatRequest,
        ChatResponse,
        ErrorResponse,
        CreateSessionRequest,    # NEW
        AppendMessageRequest,    # NEW
    )

    # --- Robust import of OpenAIService with fallback shim -------------------
    try:
        import services.openai_client as _openai_client_mod       # inline-change: absolute import
        OpenAIService = getattr(_openai_client_mod, "OpenAIService", None)  # inline-change
    except Exception:  # noqa: BLE001
        OpenAIService = None  # will define a local shim below                # inline-change

    # --- Sessions service & models (absolute imports in top-level mode) -----
    try:
        from services.session_store import (                       # <-- ADDED: sessions service imports
            create_session,
            list_sessions,
            get_session_messages,
            append_message,
            delete_session as delete_session_row,
            export_session,
        )
        from models import Session as ChatSession                  # <-- ADDED: model for existence checks
        from config import db                                      # <-- ADDED: access db.session.get
    except Exception:  # noqa: BLE001
        create_session = list_sessions = get_session_messages = append_message = delete_session_row = export_session = None  # type: ignore
        ChatSession = None  # type: ignore
        db = None  # type: ignore
else:  # <-- CHANGED: mode-aware imports for package launch (server.app:app)
    from .config import app  # preferred in package context
    from .observability import (
        init_logging,
        register_request_id,
        register_latency_logging,
        register_error_handlers,
    )
    from .security import register_security_headers
    from .ratelimit import init_rate_limiter
    from .schemas import (                                         # <-- CHANGED: import new DTOs
        ChatRequest,
        ChatResponse,
        ErrorResponse,
        CreateSessionRequest,    # NEW
        AppendMessageRequest,    # NEW
    )

    # --- Robust import of OpenAIService with fallback shim -------------------
    try:
        from .services import openai_client as _openai_client_mod   # inline-change: relative import in package mode
        OpenAIService = getattr(_openai_client_mod, "OpenAIService", None)  # inline-change
    except Exception:  # noqa: BLE001
        OpenAIService = None  # will define a local shim below                # inline-change

    # --- Sessions service & models (package imports) ------------------------
    try:
        from .services.session_store import (                        # <-- ADDED: sessions service imports
            create_session,
            list_sessions,
            get_session_messages,
            append_message,
            delete_session as delete_session_row,
            export_session,
        )
        from .models import Session as ChatSession                   # <-- ADDED: model for existence checks
        from .config import db                                       # <-- ADDED: access db.session.get
    except Exception:  # noqa: BLE001
        create_session = list_sessions = get_session_messages = append_message = delete_session_row = export_session = None  # type: ignore
        ChatSession = None  # type: ignore
        db = None  # type: ignore
# ------------------------------------------------------------------------------------------------

load_dotenv()

# ---------------------- Fallback shim (deploy unblocks even if import fails) -----------------
# If OpenAIService couldn't be imported (e.g., naming/version mismatch), provide a minimal
# drop-in with the same interface so the app still runs. This uses the raw OpenAI client
# directly (no retries/breaker), preserving previous behavior.
if OpenAIService is None:  # <-- CHANGED: define shim only when needed
    class OpenAIService:  # type: ignore[redefinition-of-class]
        def __init__(self, client, logger=None, **_kwargs):
            self._client = client
            self._logger = logger

        def complete(self, model: str, messages):
            resp = self._client.chat.completions.create(
                model=model,
                messages=messages,
            )
            # best-effort usage log (kept consistent with prior behavior)
            try:
                usage = getattr(resp, "usage", None)
                if self._logger:
                    extra = {"event": "openai.chat.complete", "model": model}
                    if usage:
                        extra.update({
                            "prompt_tokens": getattr(usage, "prompt_tokens", None),
                            "completion_tokens": getattr(usage, "completion_tokens", None),
                            "total_tokens": getattr(usage, "total_tokens", None),
                        })
                    self._logger.info("openai chat complete", extra=extra)
            except Exception:  # noqa: BLE001
                pass
            return (resp.choices[0].message.content or "").strip()

        def stream(self, model: str, messages):
            stream = self._client.chat.completions.create(
                model=model,
                messages=messages,
                stream=True,
            )
            for chunk in stream:
                try:
                    delta = chunk.choices[0].delta
                    token = getattr(delta, "content", None)
                    if token:
                        yield token
                except Exception:  # noqa: BLE001
                    continue
# ------------------------------------------------------------------------------------------------

# Robust OpenAI client: retries + timeout (SDK also has internal retries)
client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    max_retries=2,     # retry transient failures a couple times
    timeout=30.0,      # hard deadline per request (seconds)
)

# Instantiate OpenAIService with logger for structured logs
openai_service = OpenAIService(
    client=client,
    logger=app.logger,           # pass Flask logger into service
    timeout=30.0,
    max_retries=2,
    breaker_threshold=3,
    breaker_cooldown=20.0,
)

# ---------------------- Cross-cutting initialization ----------------------
init_logging(app)                 # JSON logs to stdout
register_request_id(app)          # X-Request-ID + g.request_id
register_latency_logging(app)     # one structured access log per request
register_error_handlers(app)      # JSON error shape for /api/*
register_security_headers(app)    # CSP/HSTS/nosniff/referrer/xfo
# -------------------------------------------------------------------------


def _error_payload(message: str, code: int):  # <-- ADDED: small helper to unify JSON error bodies
    return {
        "error": message,
        "code": code,
        "request_id": getattr(g, "request_id", None),
    }


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200  # for Render health checks

# --------------------------- API ROUTES -----------------------------------
@app.route("/api/chat", methods=["POST"])
def chat():
    """
    Non-streaming chat endpoint.
    Uses Pydantic DTOs for validation and OpenAIService for calls.
    Optionally appends messages to a session when a valid session_id is provided.
    """
    data = request.get_json(silent=True)
    if not data or "message" not in data:  # preserve original 400 for missing 'message'
        return jsonify(_error_payload("Missing JSON body or 'message' field", 400)), 400  # <-- CHANGED: unified shape

    incoming_message = (data.get("message") or "").strip()  # trim for guardrail + DTO min_length
    model = data.get("model", "gpt-3.5-turbo")

    if len(incoming_message) > 4000:  # preserve 413 semantics
        raise RequestEntityTooLarge(description="Message too large")  # <-- CHANGED: raise HTTPException so global handler shapes JSON

    try:
        req = ChatRequest(message=incoming_message, model=model, session_id=data.get("session_id"))  # <-- CHANGED: support optional session_id
    except ValidationError as ve:
        # Return unified 400 with details list for FE mapping
        payload = _error_payload("Validation error", 400)  # <-- CHANGED: unified shape
        payload["details"] = ve.errors()                   # <-- CHANGED: include Pydantic errors
        return jsonify(payload), 400

    messages = [
        {"role": "system", "content": "You are a helpful assistant."},  # system prompt unchanged
        {"role": "user", "content": req.message},
    ]

    # --- NEW: persist user/assistant messages if session exists -------------
    session_exists = False
    if req.session_id and db is not None and ChatSession is not None:
        try:
            session_exists = db.session.get(ChatSession, req.session_id) is not None  # <-- ADDED: existence check
            if session_exists:
                append_message(req.session_id, "user", req.message)  # <-- ADDED: persist user message
        except Exception:
            session_exists = False  # swallow persistence errors to not affect chat

    try:
        reply_text = openai_service.complete(model=req.model, messages=messages)
        # If we have a valid session, store assistant reply as well
        if session_exists:
            try:
                append_message(req.session_id, "assistant", reply_text)  # <-- ADDED: persist assistant reply
            except Exception:
                pass

        resp = ChatResponse(reply=reply_text)
        return jsonify(resp.model_dump())
    except RuntimeError as exc:
        # Explicit handling for circuit breaker open
        if str(exc) == "circuit_open":
            current_app.logger.warning(
                "openai.circuit_open",
                extra={"event": "breaker.open", "request_id": getattr(g, "request_id", None)},
            )
            return jsonify(_error_payload("Service temporarily unavailable", 503)), 503  # <-- CHANGED: unified shape
        # Otherwise generic 500 with unified error body
        current_app.logger.error(
            "openai.chat.error",
            exc_info=True,
            extra={
                "event": "openai.chat.error",
                "request_id": getattr(g, "request_id", None),
                "model": req.model,
            },
        )
        return jsonify(_error_payload(str(exc), 500)), 500  # <-- CHANGED: unified shape
    except Exception as e:
        # Log exception with request_id and return unified error shape
        current_app.logger.error(
            "openai.chat.error",
            exc_info=True,
            extra={
                "event": "openai.chat.error",
                "request_id": getattr(g, "request_id", None),
                "model": req.model,
            },
        )
        return jsonify(_error_payload(str(e), 500)), 500  # <-- CHANGED: unified shape


@app.route("/api/chat/stream", methods=["POST"])
def chat_stream():
    """
    Stream assistant tokens via Server-Sent Events (SSE).
    Validates via DTOs and streams via OpenAIService.
    Optionally appends messages to a session when a valid session_id is provided.
    """
    data = request.get_json(silent=True)
    if not data or "message" not in data:  # preserve original 400 for missing 'message'
        return jsonify(_error_payload("Missing JSON body or 'message' field", 400)), 400  # <-- CHANGED: unified shape

    incoming_message = (data.get("message") or "").strip()
    model = data.get("model", "gpt-3.5-turbo")

    if len(incoming_message) > 4000:
        raise RequestEntityTooLarge(description="Message too large")  # <-- CHANGED: raise HTTPException so global handler shapes JSON

    try:
        req = ChatRequest(message=incoming_message, model=model, session_id=data.get("session_id"))  # <-- CHANGED: support optional session_id
    except ValidationError as ve:
        payload = _error_payload("Validation error", 400)  # <-- CHANGED: unified shape
        payload["details"] = ve.errors()                   # <-- CHANGED: include Pydantic errors
        return jsonify(payload), 400

    # Log stream start for correlation
    current_app.logger.info(
        "openai.chat.stream.start",
        extra={
            "event": "openai.chat.stream.start",
            "request_id": getattr(g, "request_id", None),
            "model": req.model,
        },
    )

    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": req.message},
    ]

    @stream_with_context  # keep Flask ctx during generator
    def generate():
        import json
        rid = getattr(g, "request_id", None)  # <-- ADDED: capture once to reuse in frames
        assembled = []  # <-- ADDED: collect streamed tokens for DB append at end
        session_exists = False

        # If a valid session is provided, persist the user message now
        if req.session_id and db is not None and ChatSession is not None:
            try:
                session_exists = db.session.get(ChatSession, req.session_id) is not None  # <-- ADDED
                if session_exists:
                    append_message(req.session_id, "user", req.message)  # <-- ADDED
            except Exception:
                session_exists = False

        try:
            # Emit an initial event with the request_id for client correlation
            init_payload = {"request_id": rid}
            yield f"data: {json.dumps(init_payload)}\n\n"  # initial SSE message

            # Stream tokens
            for token in openai_service.stream(model=req.model, messages=messages):
                assembled.append(token)  # <-- ADDED: capture for DB persistence
                payload = {"token": token}
                yield f"data: {json.dumps(payload)}\n\n"

            # Final done marker
            yield f"data: {json.dumps({'done': True})}\n\n"

            # Persist assistant message at the end if session is valid
            if session_exists:
                try:
                    append_message(req.session_id, "assistant", "".join(assembled))  # <-- ADDED
                except Exception:
                    pass

            # Log completion (usage typically unavailable in stream)
            current_app.logger.info(
                "openai.chat.stream.complete",
                extra={
                    "event": "openai.chat.stream.complete",
                    "request_id": rid,
                    "model": req.model,
                    "prompt_tokens": None,
                    "completion_tokens": None,
                    "total_tokens": None,
                },
            )
        except RuntimeError as exc:
            # Circuit breaker surfaced as a terminal event
            if str(exc) == "circuit_open":
                current_app.logger.warning(
                    "openai.circuit_open",
                    extra={
                        "event": "breaker.open",
                        "request_id": rid,
                        "model": req.model,
                    },
                )
                # <-- CHANGED: include unified fields in SSE error frame
                yield f"data: {json.dumps({'error': 'Service temporarily unavailable', 'code': 503, 'request_id': rid, 'done': True})}\n\n"
                return
            # Other runtime errors → log and emit terminal error frame
            current_app.logger.error(
                "openai.chat.stream.error",
                exc_info=True,
                extra={
                    "event": "openai.chat.stream.error",
                    "request_id": rid,
                    "model": req.model,
                },
            )
            # <-- CHANGED: include code 500 + request_id
            yield f"data: {json.dumps({'error': str(exc), 'code': 500, 'request_id': rid, 'done': True})}\n\n"
        except Exception as e:
            # Generic exceptions → log and emit terminal error frame
            current_app.logger.error(
                "openai.chat.stream.error",
                exc_info=True,
                extra={
                    "event": "openai.chat.stream.error",
                    "request_id": rid,
                    "model": req.model,
                },
            )
            # <-- CHANGED: include code 500 + request_id
            yield f"data: {json.dumps({'error': str(e), 'code': 500, 'request_id': rid, 'done': True})}\n\n"

    # Stream-friendly headers (avoid proxy buffering)
    headers = {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
    }
    return Response(generate(), mimetype="text/event-stream", headers=headers)
# -------------------------------------------------------------------------

# --------------------------- SESSIONS API ---------------------------------
@app.route("/api/sessions", methods=["POST"])
def create_session_route():
    """Create a new chat session (optional title)."""
    data = request.get_json(silent=True) or {}
    try:
        req = CreateSessionRequest(**data)  # <-- ADDED: DTO validation
    except ValidationError as ve:
        payload = _error_payload("Validation error", 400)
        payload["details"] = ve.errors()
        return jsonify(payload), 400

    try:
        s = create_session(title=req.title)  # type: ignore[arg-type]
    except Exception as e:
        current_app.logger.error("session.create.error", exc_info=True, extra={"event": "session.create", "title": req.title})
        return jsonify(_error_payload(str(e), 500)), 500

    current_app.logger.info("session.create", extra={"event": "session.create", "session_id": s.id, "title": s.title})
    return jsonify({
        "id": s.id,
        "title": s.title,
        "created_at": (s.created_at.isoformat() if getattr(s, "created_at", None) else None),
        "updated_at": (s.updated_at.isoformat() if getattr(s, "updated_at", None) else None),
    }), 200  # 200 is fine for creation here


@app.route("/api/sessions", methods=["GET"])
def list_sessions_route():
    """List sessions with last activity."""
    try:
        rows = list_sessions()
    except Exception as e:
        current_app.logger.error("session.list.error", exc_info=True, extra={"event": "session.list"})
        return jsonify(_error_payload(str(e), 500)), 500

    def _fmt(r):
        return {
            "id": r["id"],
            "title": r["title"],
            "created_at": (r["created_at"].isoformat() if r.get("created_at") else None),
            "last_activity": (r["last_activity"].isoformat() if r.get("last_activity") else None),
        }

    return jsonify([_fmt(r) for r in rows]), 200


@app.route("/api/sessions/<session_id>", methods=["GET"])
def get_session_route(session_id: str):
    """Get messages for a session (ascending by created_at)."""
    if db is None or ChatSession is None:
        return jsonify(_error_payload("Sessions not available", 500)), 500

    s = db.session.get(ChatSession, session_id)
    if not s:
        return jsonify(_error_payload("Session not found", 404)), 404

    try:
        msgs = get_session_messages(session_id)
    except Exception as e:
        current_app.logger.error("session.get.error", exc_info=True, extra={"event": "session.get", "session_id": session_id})
        return jsonify(_error_payload(str(e), 500)), 500

    # Ensure ISO dates for FE
    for m in msgs:
        if m.get("created_at"):
            m["created_at"] = m["created_at"].isoformat()

    return jsonify({
        "id": s.id,
        "title": s.title,
        "created_at": (s.created_at.isoformat() if getattr(s, "created_at", None) else None),
        "updated_at": (s.updated_at.isoformat() if getattr(s, "updated_at", None) else None),
        "messages": msgs,
    }), 200


@app.route("/api/sessions/<session_id>/messages", methods=["POST"])
def append_message_route(session_id: str):
    """Append a single message to a session."""
    if db is None or ChatSession is None:
        return jsonify(_error_payload("Sessions not available", 500)), 500

    s = db.session.get(ChatSession, session_id)
    if not s:
        return jsonify(_error_payload("Session not found", 404)), 404

    data = request.get_json(silent=True) or {}
    try:
        req = AppendMessageRequest(**data)  # <-- ADDED: DTO validation
    except ValidationError as ve:
        payload = _error_payload("Validation error", 400)
        payload["details"] = ve.errors()
        return jsonify(payload), 400

    try:
        m = append_message(session_id, req.role, req.content, req.tokens)
        current_app.logger.info("message.append", extra={"event": "message.append", "session_id": session_id, "role": req.role})
        return jsonify({
            "id": m.id,
            "role": str(m.role),
            "content": m.content,
            "tokens": m.tokens,
            "created_at": (m.created_at.isoformat() if getattr(m, "created_at", None) else None),
        }), 201  # created
    except ValueError:
        return jsonify(_error_payload("Session not found", 404)), 404
    except Exception as e:
        current_app.logger.error("message.append.error", exc_info=True, extra={"event": "message.append", "session_id": session_id})
        return jsonify(_error_payload(str(e), 500)), 500


@app.route("/api/sessions/<session_id>", methods=["DELETE"])
def delete_session_route(session_id: str):
    """Delete a session and cascade messages."""
    try:
        ok = delete_session_row(session_id)
    except Exception as e:
        current_app.logger.error("session.delete.error", exc_info=True, extra={"event": "session.delete", "session_id": session_id})
        return jsonify(_error_payload(str(e), 500)), 500

    if not ok:
        return jsonify(_error_payload("Session not found", 404)), 404

    current_app.logger.info("session.delete", extra={"event": "session.delete", "session_id": session_id})
    return ("", 204)  # no content


@app.route("/api/sessions/<session_id>/export", methods=["GET"])
def export_session_route(session_id: str):
    """Export a session as JSON or Markdown (download)."""
    fmt = (request.args.get("format") or "json").lower()
    if fmt not in ("json", "md"):
        return jsonify(_error_payload("Invalid format; use json|md", 400)), 400

    if db is None or ChatSession is None:
        return jsonify(_error_payload("Sessions not available", 500)), 500

    s = db.session.get(ChatSession, session_id)
    if not s:
        return jsonify(_error_payload("Session not found", 404)), 404

    try:
        name, data_bytes, mime = export_session(session_id, fmt)
        current_app.logger.info("session.export", extra={"event": "session.export", "session_id": session_id, "format": fmt})
        headers = {
            "Content-Type": mime,
            "Content-Disposition": f'attachment; filename="{name}"',
        }
        return Response(data_bytes, headers=headers)
    except Exception as e:
        current_app.logger.error("session.export.error", exc_info=True, extra={"event": "session.export", "session_id": session_id})
        return jsonify(_error_payload(str(e), 500)), 500
# -------------------------------------------------------------------------

# ---------------------- SPA FALLBACK FOR ROUTING -------------------------
# Any non-API 404 returns the built index.html so client-side routes work.
@app.errorhandler(404)
def not_found(_e):
    # Global error handlers intentionally skip non-/api paths
    return render_template("index.html")
# -------------------------------------------------------------------------

# >>> Initialize rate limiter AFTER routes are registered
init_rate_limiter(app)

if __name__ == "__main__":
    # Local dev convenience; Render uses gunicorn
    app.run(debug=True)
