# server/app.py
# Flask serves ../client/dist and exposes /api routes

# >>> Import the Flask app with a package-safe pattern so it works under
# gunicorn --chdir server (relative import) AND when run locally (absolute).
try:
    from .config import app  # preferred in package context
except ImportError:  # running as a script (e.g., python server/app.py)
    from config import app  # fallback

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

# >>> Same package-safe import pattern for our internal modules.
try:
    from .observability import (  # JSON logging & middleware
        init_logging,
        register_request_id,
        register_latency_logging,
        register_error_handlers,
    )
    from .security import register_security_headers  # security headers
    from .ratelimit import init_rate_limiter        # rate limiting
    from .schemas import ChatRequest, ChatResponse, ErrorResponse  # <-- CHANGED: import DTOs
    from .services.openai_client import OpenAIService              # <-- CHANGED: import service façade
except ImportError:
    from observability import (
        init_logging,
        register_request_id,
        register_latency_logging,
        register_error_handlers,
    )
    from security import register_security_headers
    from ratelimit import init_rate_limiter
    from schemas import ChatRequest, ChatResponse, ErrorResponse   # <-- CHANGED: import DTOs (abs)
    from services.openai_client import OpenAIService               # <-- CHANGED: import service façade (abs)

from pydantic import ValidationError  # <-- CHANGED: handle DTO validation errors

load_dotenv()

# Robust OpenAI client: retries + timeout
client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    max_retries=2,     # retry transient failures a couple times
    timeout=30.0,      # hard deadline per request (seconds)
)

# <-- CHANGED: instantiate OpenAIService with logger for structured logs
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


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200  # for Render health checks

# --------------------------- API ROUTES -----------------------------------
@app.route("/api/chat", methods=["POST"])
def chat():
    """
    Non-streaming chat endpoint.
    CHANGED: Uses Pydantic DTOs for validation and OpenAIService for calls.
    """
    data = request.get_json(silent=True)
    if not data or "message" not in data:  # <-- CHANGED: preserve original 400 for missing 'message'
        return jsonify({"error": "Missing JSON body or 'message' field"}), 400  # validation

    # <-- CHANGED: trim early to preserve previous behavior and clearer 413 logic
    incoming_message = (data.get("message") or "").strip()
    model = data.get("model", "gpt-3.5-turbo")

    # <-- CHANGED: preserve 413 semantics from previous implementation
    if len(incoming_message) > 4000:
        return jsonify({"error": "Message too large"}), 413

    # <-- CHANGED: Validate with DTOs (min_length, allowed models)
    try:
        req = ChatRequest(message=incoming_message, model=model)
    except ValidationError as ve:
        # Map DTO failures to a 400 response; keep shape simple
        return jsonify({"error": ve.errors()}), 400

    messages = [
        {"role": "system", "content": "You are a helpful assistant."},  # unchanged system prompt
        {"role": "user", "content": req.message},
    ]

    try:
        # <-- CHANGED: use service façade (handles retries, breaker, logs)
        reply_text = openai_service.complete(model=req.model, messages=messages)

        # <-- CHANGED: shape via DTO for clarity (optional)
        resp = ChatResponse(reply=reply_text)
        return jsonify(resp.model_dump())
    except RuntimeError as exc:
        # <-- CHANGED: explicit handling for circuit breaker open
        if str(exc) == "circuit_open":
            current_app.logger.warning(
                "openai.circuit_open",
                extra={"event": "breaker.open", "request_id": getattr(g, "request_id", None)},
            )
            return jsonify({"error": "Service temporarily unavailable"}), 503
        # Otherwise fall through to generic 500 with original behavior
        current_app.logger.error(
            "openai.chat.error",
            exc_info=True,
            extra={
                "event": "openai.chat.error",
                "request_id": getattr(g, "request_id", None),
                "model": req.model,
            },
        )
        return jsonify({"error": str(exc)}), 500  # <-- CHANGED: preserve previous error body
    except Exception as e:
        # Unchanged: log exception with request_id and return prior error shape
        current_app.logger.error(
            "openai.chat.error",
            exc_info=True,
            extra={
                "event": "openai.chat.error",
                "request_id": getattr(g, "request_id", None),
                "model": req.model,
            },
        )
        return jsonify({"error": str(e)}), 500  # <-- CHANGED: preserve previous error body


@app.route("/api/chat/stream", methods=["POST"])
def chat_stream():
    """
    Stream assistant tokens via Server-Sent Events (SSE).
    Keeps existing /api/chat unchanged for graceful fallback.
    CHANGED: Validates via DTOs and streams via OpenAIService.
    """
    data = request.get_json(silent=True)
    if not data or "message" not in data:  # <-- CHANGED: preserve original 400 for missing 'message'
        return jsonify({"error": "Missing JSON body or 'message' field"}), 400  # validation

    incoming_message = (data.get("message") or "").strip()
    model = data.get("model", "gpt-3.5-turbo")

    # Same guardrail to preserve prior 413 behavior
    if len(incoming_message) > 4000:
        return jsonify({"error": "Message too large"}), 413

    try:
        req = ChatRequest(message=incoming_message, model=model)  # <-- CHANGED: DTO validation
    except ValidationError as ve:
        return jsonify({"error": ve.errors()}), 400

    # Log stream start for correlation (unchanged)
    current_app.logger.info(
        "openai.chat.stream.start",
        extra={
            "event": "openai.chat.stream.start",
            "request_id": getattr(g, "request_id", None),
            "model": req.model,
        },
    )

    messages = [
        {"role": "system", "content": "You are a helpful assistant."},  # unchanged system prompt
        {"role": "user", "content": req.message},
    ]

    @stream_with_context  # keep Flask ctx during generator
    def generate():
        import json
        try:
            # <-- CHANGED: stream via service façade (yields str tokens)
            # Emit an initial event with the request_id for client correlation
            init_payload = {"request_id": getattr(g, "request_id", None)}
            yield f"data: {json.dumps(init_payload)}\n\n"  # unchanged framing

            for token in openai_service.stream(model=req.model, messages=messages):
                payload = {"token": token}
                yield f"data: {json.dumps(payload)}\n\n"  # unchanged per-token SSE

            # Final event to signal completion (unchanged)
            done_payload = {"done": True}
            yield f"data: {json.dumps(done_payload)}\n\n"

            # Log completion (usage typically unavailable in stream)
            current_app.logger.info(
                "openai.chat.stream.complete",
                extra={
                    "event": "openai.chat.stream.complete",
                    "request_id": getattr(g, "request_id", None),
                    "model": req.model,
                    "prompt_tokens": None,
                    "completion_tokens": None,
                    "total_tokens": None,
                },
            )
        except RuntimeError as exc:
            # <-- CHANGED: circuit breaker surfaced as 503-equivalent terminal event
            if str(exc) == "circuit_open":
                current_app.logger.warning(
                    "openai.circuit_open",
                    extra={
                        "event": "breaker.open",
                        "request_id": getattr(g, "request_id", None),
                        "model": req.model,
                    },
                )
                err_payload = {"error": "Service temporarily unavailable", "done": True}
                yield f"data: {json.dumps(err_payload)}\n\n"
                return
            # Other runtime errors → log and emit terminal error frame
            current_app.logger.error(
                "openai.chat.stream.error",
                exc_info=True,
                extra={
                    "event": "openai.chat.stream.error",
                    "request_id": getattr(g, "request_id", None),
                    "model": req.model,
                },
            )
            err_payload = {"error": str(exc), "done": True}  # <-- CHANGED: preserve previous error body
            yield f"data: {json.dumps(err_payload)}\n\n"
        except Exception as e:
            # Generic exceptions → log and emit terminal error frame
            current_app.logger.error(
                "openai.chat.stream.error",
                exc_info=True,
                extra={
                    "event": "openai.chat.stream.error",
                    "request_id": getattr(g, "request_id", None),
                    "model": req.model,
                },
            )
            err_payload = {"error": str(e), "done": True}  # <-- CHANGED: preserve previous error body
            yield f"data: {json.dumps(err_payload)}\n\n"

    # Stream-friendly headers (avoid proxy buffering)
    headers = {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
    }
    return Response(generate(), mimetype="text/event-stream", headers=headers)
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
