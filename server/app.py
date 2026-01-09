# server/app.py
# Flask serves ../client/dist and exposes /api routes

import importlib
import os

from dotenv import load_dotenv
from flask import (
    Response,
    current_app,
    g,
    jsonify,
    render_template,
    request,
    stream_with_context,
)
from openai import OpenAI
from pydantic import ValidationError
from werkzeug.exceptions import RequestEntityTooLarge

# Import strategy: works in both launch modes.
# - gunicorn --chdir server app:app  -> top-level module, use absolute imports
# - gunicorn server.app:app          -> package module, use relative imports
if __package__ in (None, ""):  # top-level launch: gunicorn --chdir server app:app
    from config import app
    from observability import (
        init_logging,
        register_error_handlers,
        register_latency_logging,
        register_request_id,
    )
    from ratelimit import init_rate_limiter
    from routes.rag import rag_bp
    from schemas import (
        AppendMessageRequest,
        ChatRequest,
        ChatResponse,
        CreateSessionRequest,
        UpdateSessionRequest,
    )
    from security import register_security_headers

    try:
        import services.openai_client as _openai_client_mod

        OpenAIService = getattr(_openai_client_mod, "OpenAIService", None)
    except Exception:  # noqa: BLE001
        OpenAIService = None

    try:
        import services.session_store as session_store
    except Exception:  # noqa: BLE001
        session_store = None

    try:
        from config import db
        from models import Session as ChatSession
    except Exception:  # noqa: BLE001
        ChatSession = None  # type: ignore
        db = None  # type: ignore

else:  # package launch: gunicorn server.app:app
    from .config import app
    from .observability import (
        init_logging,
        register_error_handlers,
        register_latency_logging,
        register_request_id,
    )
    from .ratelimit import init_rate_limiter
    from .routes.rag import rag_bp
    from .schemas import (
        AppendMessageRequest,
        ChatRequest,
        ChatResponse,
        CreateSessionRequest,
        UpdateSessionRequest,
    )
    from .security import register_security_headers

    try:
        from .services import openai_client as _openai_client_mod

        OpenAIService = getattr(_openai_client_mod, "OpenAIService", None)
    except Exception:  # noqa: BLE001
        OpenAIService = None

    try:
        from .services import session_store as session_store
    except Exception:  # noqa: BLE001
        session_store = None

    try:
        from .config import db
        from .models import Session as ChatSession
    except Exception:  # noqa: BLE001
        ChatSession = None  # type: ignore
        db = None  # type: ignore


load_dotenv()

if OpenAIService is None:

    class OpenAIService:  # type: ignore[redefinition-of-class]
        def __init__(self, client, logger=None, **_kwargs):
            self._client = client
            self._logger = logger

        def complete(self, model: str, messages):
            resp = self._client.chat.completions.create(
                model=model,
                messages=messages,
            )
            try:
                usage = getattr(resp, "usage", None)
                if self._logger:
                    extra = {"event": "openai.chat.complete", "model": model}
                    if usage:
                        extra.update(
                            {
                                "prompt_tokens": getattr(usage, "prompt_tokens", None),
                                "completion_tokens": getattr(
                                    usage, "completion_tokens", None
                                ),
                                "total_tokens": getattr(usage, "total_tokens", None),
                            }
                        )
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


client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    max_retries=2,
    timeout=30.0,
)

openai_service = OpenAIService(
    client=client,
    logger=app.logger,
    timeout=30.0,
    max_retries=2,
    breaker_threshold=3,
    breaker_cooldown=20.0,
)

init_logging(app)
register_request_id(app)
register_latency_logging(app)
register_error_handlers(app)
register_security_headers(app)

app.register_blueprint(rag_bp, url_prefix="/api/rag")


def _error_payload(message: str, code: int):
    return {
        "error": message,
        "code": code,
        "request_id": getattr(g, "request_id", None),
    }


def _validation_details(exc: ValidationError):
    try:
        details = []
        for err in exc.errors():
            ctx = err.get("ctx")
            if isinstance(ctx, dict):
                err = err.copy()
                err["ctx"] = {
                    k: (str(v) if isinstance(v, BaseException) else v)
                    for k, v in ctx.items()
                }
            details.append(err)
        return details
    except Exception:
        return [{"msg": str(exc)}]


def _ensure_sessions_service():
    global session_store
    if session_store is None:
        try:
            session_store = importlib.import_module("server.services.session_store")
        except Exception as e1:
            try:
                session_store = importlib.import_module("services.session_store")
            except Exception as e2:
                current_app.logger.error(
                    "sessions.service.import_error",
                    exc_info=True,
                    extra={
                        "event": "sessions.service.import_error",
                        "err1": repr(e1),
                        "err2": repr(e2),
                    },
                )
                return jsonify(_error_payload("Internal Server Error", 500)), 500
    return None


def _memory_enabled() -> bool:
    return os.getenv("CHAT_MEMORY_ENABLED", "true").lower() not in ("0", "false", "no")


def _memory_model(default_chat_model: str) -> str:
    return os.getenv("CHAT_MEMORY_MODEL", "gpt-3.5-turbo") or default_chat_model


def _memory_max_chars() -> int:
    try:
        return max(200, int(os.getenv("CHAT_MEMORY_MAX_CHARS", "2000")))
    except Exception:
        return 2000


def _summarize_and_merge_memory(
    session_id: str,
    old_memory: str | None,
    last_user: str,
    last_assistant: str,
    chat_model: str,
):
    if not _memory_enabled():
        return

    err = _ensure_sessions_service()
    if err:
        return

    try:
        max_chars = _memory_max_chars()
        sys_prompt = (
            "You are a compact session memory manager. Merge the old memory with the "
            "latest user/assistant turn into a concise, de-duplicated bullet list of "
            "persistent facts, preferences, goals, and decisions. Omit chit-chat, "
            "speculation, and ephemeral details. "
            f"Keep the result under {max_chars} characters. Return plain text."
        )
        user_block = (
            f"Old memory:\n{old_memory or '(none)'}\n\n"
            f"Latest turn:\nUser: {last_user}\nAssistant: {last_assistant}\n\n"
            "Return the UPDATED MEMORY ONLY."
        )
        messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_block},
        ]
        mem_model = _memory_model(chat_model)
        new_mem = (
            openai_service.complete(model=mem_model, messages=messages) or ""
        ).strip()
        if not new_mem:
            new_mem = old_memory or ""

        if len(new_mem) > max_chars:
            new_mem = new_mem[:max_chars]

        session_store.update_memory(session_id, new_mem)
        current_app.logger.info(
            "session.memory.updated",
            extra={
                "event": "session.memory.updated",
                "session_id": session_id,
                "chars": len(new_mem),
                "used_model": mem_model,
            },
        )
    except Exception:
        current_app.logger.warning(
            "session.memory.update_failed",
            exc_info=True,
            extra={"event": "session.memory.update_failed", "session_id": session_id},
        )


def _build_openai_messages_with_context(
    user_text: str, model: str, session_id: str | None
):
    SYSTEM_PROMPT = "You are a helpful assistant."
    MAX_TURNS = int(os.getenv("CHAT_CONTEXT_MAX_TURNS", "12"))

    msgs = [{"role": "system", "content": SYSTEM_PROMPT}]

    if _memory_enabled() and session_id and db is not None and ChatSession is not None:
        if _ensure_sessions_service() is None:
            try:
                pinned = session_store.get_memory(session_id)
                if pinned:
                    msgs.append(
                        {
                            "role": "system",
                            "content": f"Session memory (pinned):\n{pinned}",
                        }
                    )
            except Exception:
                current_app.logger.warning(
                    "sessions.memory.load_failed",
                    exc_info=True,
                    extra={
                        "event": "sessions.memory.load_failed",
                        "session_id": session_id,
                    },
                )

    if session_id and db is not None and ChatSession is not None:
        if _ensure_sessions_service() is None:
            try:
                prior = session_store.get_session_messages(session_id) or []

                keep = MAX_TURNS * 2
                if keep <= 0:
                    prior = []
                elif len(prior) > keep:
                    prior = prior[-keep:]

                for m in prior:
                    role = "assistant" if m.get("role") == "assistant" else "user"
                    content = m.get("content") or ""
                    if content:
                        msgs.append({"role": role, "content": content})
            except Exception:
                current_app.logger.warning(
                    "sessions.context.load_failed",
                    exc_info=True,
                    extra={
                        "event": "sessions.context.load_failed",
                        "session_id": session_id,
                    },
                )

    msgs.append({"role": "user", "content": user_text})
    return msgs


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.get_json(silent=True)
    if not data or "message" not in data:
        return jsonify(_error_payload("Missing JSON body or 'message' field", 400)), 400

    incoming_message = (data.get("message") or "").strip()
    model = data.get("model", "gpt-3.5-turbo")

    if len(incoming_message) > 4000:
        raise RequestEntityTooLarge(description="Message too large")

    try:
        req = ChatRequest(
            message=incoming_message, model=model, session_id=data.get("session_id")
        )
    except ValidationError as ve:
        payload = _error_payload("Validation error", 400)
        payload["details"] = _validation_details(ve)
        return jsonify(payload), 400

    messages = _build_openai_messages_with_context(
        req.message,
        req.model,
        req.session_id,
    )

    session_exists = False
    if req.session_id and db is not None and ChatSession is not None:
        if _ensure_sessions_service() is None:
            try:
                session_exists = db.session.get(ChatSession, req.session_id) is not None
            except Exception:
                session_exists = False

    try:
        reply_text = openai_service.complete(model=req.model, messages=messages)
        if session_exists:
            try:
                session_store.append_message(req.session_id, "user", req.message)
                session_store.append_message(req.session_id, "assistant", reply_text)
                _summarize_and_merge_memory(
                    session_id=req.session_id,
                    old_memory=session_store.get_memory(req.session_id),
                    last_user=req.message,
                    last_assistant=reply_text,
                    chat_model=req.model,
                )
            except Exception:
                current_app.logger.warning(
                    "session.persist_or_memory.failed",
                    exc_info=True,
                    extra={
                        "event": "session.persist_or_memory.failed",
                        "session_id": req.session_id,
                    },
                )

        resp = ChatResponse(reply=reply_text)
        return jsonify(resp.model_dump())
    except RuntimeError as exc:
        if str(exc) == "circuit_open":
            current_app.logger.warning(
                "openai.circuit_open",
                extra={
                    "event": "breaker.open",
                    "request_id": getattr(g, "request_id", None),
                },
            )
            return jsonify(_error_payload("Service temporarily unavailable", 503)), 503
        current_app.logger.error(
            "openai.chat.error",
            exc_info=True,
            extra={
                "event": "openai.chat.error",
                "request_id": getattr(g, "request_id", None),
                "model": req.model,
            },
        )
        return jsonify(_error_payload(str(exc), 500)), 500
    except Exception as e:
        current_app.logger.error(
            "openai.chat.error",
            exc_info=True,
            extra={
                "event": "openai.chat.error",
                "request_id": getattr(g, "request_id", None),
                "model": req.model,
            },
        )
        return jsonify(_error_payload(str(e), 500)), 500


@app.route("/api/chat/stream", methods=["POST"])
def chat_stream():
    data = request.get_json(silent=True)
    if not data or "message" not in data:
        return jsonify(_error_payload("Missing JSON body or 'message' field", 400)), 400

    incoming_message = (data.get("message") or "").strip()
    model = data.get("model", "gpt-3.5-turbo")

    if len(incoming_message) > 4000:
        raise RequestEntityTooLarge(description="Message too large")

    try:
        req = ChatRequest(
            message=incoming_message, model=model, session_id=data.get("session_id")
        )
    except ValidationError as ve:
        payload = _error_payload("Validation error", 400)
        payload["details"] = _validation_details(ve)
        return jsonify(payload), 400

    current_app.logger.info(
        "openai.chat.stream.start",
        extra={
            "event": "openai.chat.stream.start",
            "request_id": getattr(g, "request_id", None),
            "model": req.model,
        },
    )

    messages = _build_openai_messages_with_context(
        req.message,
        req.model,
        req.session_id,
    )

    @stream_with_context
    def generate():
        import json

        rid = getattr(g, "request_id", None)
        assembled = []
        session_exists = False

        if req.session_id and db is not None and ChatSession is not None:
            if _ensure_sessions_service() is None:
                try:
                    session_exists = (
                        db.session.get(ChatSession, req.session_id) is not None
                    )
                except Exception:
                    session_exists = False

        try:
            yield f"data: {json.dumps({'request_id': rid})}\n\n"
            for token in openai_service.stream(model=req.model, messages=messages):
                assembled.append(token)
                yield f"data: {json.dumps({'token': token})}\n\n"
            yield f"data: {json.dumps({'done': True})}\n\n"

            if session_exists:
                try:
                    session_store.append_message(req.session_id, "user", req.message)
                    assistant_text = "".join(assembled)
                    session_store.append_message(
                        req.session_id,
                        "assistant",
                        assistant_text,
                    )
                    _summarize_and_merge_memory(
                        session_id=req.session_id,
                        old_memory=session_store.get_memory(req.session_id),
                        last_user=req.message,
                        last_assistant=assistant_text,
                        chat_model=req.model,
                    )
                except Exception:
                    current_app.logger.warning(
                        "session.persist_or_memory.failed",
                        exc_info=True,
                        extra={
                            "event": "session.persist_or_memory.failed",
                            "session_id": req.session_id,
                        },
                    )

            current_app.logger.info(
                "openai.chat.stream.complete",
                extra={
                    "event": "openai.chat.stream.complete",
                    "request_id": rid,
                    "model": req.model,
                },
            )
        except RuntimeError as exc:
            if str(exc) == "circuit_open":
                current_app.logger.warning(
                    "openai.circuit_open",
                    extra={
                        "event": "breaker.open",
                        "request_id": rid,
                        "model": req.model,
                    },
                )
                payload = {
                    "error": "Service temporarily unavailable",
                    "code": 503,
                    "request_id": rid,
                    "done": True,
                }
                yield f"data: {json.dumps(payload)}\n\n"
                return
            current_app.logger.error(
                "openai.chat.stream.error",
                exc_info=True,
                extra={
                    "event": "openai.chat.stream.error",
                    "request_id": rid,
                    "model": req.model,
                },
            )
            payload = {
                "error": str(exc),
                "code": 500,
                "request_id": rid,
                "done": True,
            }
            yield f"data: {json.dumps(payload)}\n\n"
        except Exception as e:
            current_app.logger.error(
                "openai.chat.stream.error",
                exc_info=True,
                extra={
                    "event": "openai.chat.stream.error",
                    "request_id": rid,
                    "model": req.model,
                },
            )
            payload = {
                "error": str(e),
                "code": 500,
                "request_id": rid,
                "done": True,
            }
            yield f"data: {json.dumps(payload)}\n\n"

    headers = {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
    }
    return Response(generate(), mimetype="text/event-stream", headers=headers)


@app.route("/api/sessions", methods=["POST"])
def create_session_route():
    err = _ensure_sessions_service()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    try:
        req = CreateSessionRequest(**data)
    except ValidationError as ve:
        payload = _error_payload("Validation error", 400)
        payload["details"] = _validation_details(ve)
        return jsonify(payload), 400

    try:
        s = session_store.create_session(title=req.title)
    except Exception as e:
        current_app.logger.error(
            "session.create.error",
            exc_info=True,
            extra={"event": "session.create", "title": req.title},
        )
        return jsonify(_error_payload(str(e), 500)), 500

    current_app.logger.info(
        "session.create",
        extra={"event": "session.create", "session_id": s.id, "title": s.title},
    )
    return (
        jsonify(
            {
                "id": s.id,
                "title": s.title,
                "created_at": (
                    s.created_at.isoformat() if getattr(s, "created_at", None) else None
                ),
                "updated_at": (
                    s.updated_at.isoformat() if getattr(s, "updated_at", None) else None
                ),
            }
        ),
        200,
    )


@app.route("/api/sessions", methods=["GET"])
def list_sessions_route():
    err = _ensure_sessions_service()
    if err:
        return err

    try:
        rows = session_store.list_sessions()
    except Exception as e:
        current_app.logger.error(
            "session.list.error", exc_info=True, extra={"event": "session.list"}
        )
        return jsonify(_error_payload(str(e), 500)), 500

    def _fmt(r):
        return {
            "id": r["id"],
            "title": r["title"],
            "created_at": (
                r["created_at"].isoformat() if r.get("created_at") else None
            ),
            "last_activity": (
                r["last_activity"].isoformat() if r.get("last_activity") else None
            ),
        }

    return jsonify([_fmt(r) for r in rows]), 200


@app.route("/api/sessions/<session_id>", methods=["GET"])
def get_session_route(session_id: str):
    err = _ensure_sessions_service()
    if err:
        return err

    if db is None or ChatSession is None:
        return jsonify(_error_payload("Sessions not available", 500)), 500

    s = db.session.get(ChatSession, session_id)
    if not s:
        return jsonify(_error_payload("Session not found", 404)), 404

    try:
        msgs = session_store.get_session_messages(session_id)
    except Exception as e:
        current_app.logger.error(
            "session.get.error",
            exc_info=True,
            extra={"event": "session.get", "session_id": session_id},
        )
        return jsonify(_error_payload(str(e), 500)), 500

    for m in msgs:
        if m.get("created_at"):
            m["created_at"] = m["created_at"].isoformat()

    return (
        jsonify(
            {
                "id": s.id,
                "title": s.title,
                "created_at": (
                    s.created_at.isoformat() if getattr(s, "created_at", None) else None
                ),
                "updated_at": (
                    s.updated_at.isoformat() if getattr(s, "updated_at", None) else None
                ),
                "messages": msgs,
            }
        ),
        200,
    )


@app.route("/api/sessions/<session_id>/messages", methods=["POST"])
def append_message_route(session_id: str):
    err = _ensure_sessions_service()
    if err:
        return err

    if db is None or ChatSession is None:
        return jsonify(_error_payload("Sessions not available", 500)), 500

    s = db.session.get(ChatSession, session_id)
    if not s:
        return jsonify(_error_payload("Session not found", 404)), 404

    data = request.get_json(silent=True) or {}
    try:
        req = AppendMessageRequest(**data)
    except ValidationError as ve:
        payload = _error_payload("Validation error", 400)
        payload["details"] = _validation_details(ve)
        return jsonify(payload), 400

    try:
        m = session_store.append_message(session_id, req.role, req.content, req.tokens)
        current_app.logger.info(
            "message.append",
            extra={
                "event": "message.append",
                "session_id": session_id,
                "role": req.role,
            },
        )
        return (
            jsonify(
                {
                    "id": m.id,
                    "role": str(m.role),
                    "content": m.content,
                    "tokens": m.tokens,
                    "created_at": (
                        m.created_at.isoformat()
                        if getattr(m, "created_at", None)
                        else None
                    ),
                }
            ),
            201,
        )
    except ValueError:
        return jsonify(_error_payload("Session not found", 404)), 404
    except Exception as e:
        current_app.logger.error(
            "message.append.error",
            exc_info=True,
            extra={"event": "message.append", "session_id": session_id},
        )
        return jsonify(_error_payload(str(e), 500)), 500


@app.route("/api/sessions/<session_id>", methods=["PATCH"])
def rename_session_route(session_id: str):
    err = _ensure_sessions_service()
    if err:
        return err

    if db is None or ChatSession is None:
        return jsonify(_error_payload("Sessions not available", 500)), 500

    data = request.get_json(silent=True) or {}
    try:
        req = UpdateSessionRequest(**data)
    except ValidationError as ve:
        payload = _error_payload("Validation error", 400)
        payload["details"] = _validation_details(ve)
        return jsonify(payload), 400

    try:
        s = session_store.rename_session(session_id, req.title)
        current_app.logger.info(
            "session.rename",
            extra={
                "event": "session.rename",
                "session_id": session_id,
                "title": req.title,
            },
        )
        return (
            jsonify(
                {
                    "id": s.id,
                    "title": s.title,
                    "created_at": (
                        s.created_at.isoformat()
                        if getattr(s, "created_at", None)
                        else None
                    ),
                    "updated_at": (
                        s.updated_at.isoformat()
                        if getattr(s, "updated_at", None)
                        else None
                    ),
                }
            ),
            200,
        )
    except ValueError:
        return jsonify(_error_payload("Session not found", 404)), 404
    except Exception as e:
        current_app.logger.error(
            "session.rename.error",
            exc_info=True,
            extra={"event": "session.rename", "session_id": session_id},
        )
        return jsonify(_error_payload(str(e), 500)), 500


@app.route("/api/sessions/<session_id>", methods=["DELETE"])
def delete_session_route(session_id: str):
    err = _ensure_sessions_service()
    if err:
        return err

    try:
        ok = session_store.delete_session(session_id)
    except Exception as e:
        current_app.logger.error(
            "session.delete.error",
            exc_info=True,
            extra={"event": "session.delete", "session_id": session_id},
        )
        return jsonify(_error_payload(str(e), 500)), 500

    if not ok:
        return jsonify(_error_payload("Session not found", 404)), 404

    current_app.logger.info(
        "session.delete", extra={"event": "session.delete", "session_id": session_id}
    )
    return ("", 204)


@app.route("/api/sessions/<session_id>/export", methods=["GET"])
def export_session_route(session_id: str):
    err = _ensure_sessions_service()
    if err:
        return err

    fmt = (request.args.get("format") or "json").lower()
    if fmt not in ("json", "md"):
        return jsonify(_error_payload("Invalid format; use json|md", 400)), 400

    if db is None or ChatSession is None:
        return jsonify(_error_payload("Sessions not available", 500)), 500

    s = db.session.get(ChatSession, session_id)
    if not s:
        return jsonify(_error_payload("Session not found", 404)), 404

    try:
        name, data_bytes, mime = session_store.export_session(session_id, fmt)
        current_app.logger.info(
            "session.export",
            extra={"event": "session.export", "session_id": session_id, "format": fmt},
        )
        headers = {
            "Content-Type": mime,
            "Content-Disposition": f'attachment; filename="{name}"',
        }
        return Response(data_bytes, headers=headers)
    except Exception as e:
        current_app.logger.error(
            "session.export.error",
            exc_info=True,
            extra={"event": "session.export", "session_id": session_id},
        )
        return jsonify(_error_payload(str(e), 500)), 500


@app.errorhandler(404)
def not_found(_e):
    if request.path.startswith("/api/"):
        return jsonify(_error_payload("Not Found", 404)), 404
    return render_template("index.html")


init_rate_limiter(app)

if __name__ == "__main__":
    app.run(debug=True)
