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

# ---------------------- Import strategy (robust for both launch modes) ----------------------
# If launched with:  gunicorn --chdir server app:app
#   -> this module is loaded as a *top-level* module (no package), so use absolute imports.
# If launched with:  gunicorn server.app:app
#   -> this module is loaded as part of the 'server' package, so use relative imports.
if __package__ in (None, ""):  # <-- CHANGED: mode-aware imports for top-level launch
    from config import app  # load Flask app instance
    from observability import (  # JSON logging & middleware
        init_logging,
        register_request_id,
        register_latency_logging,
        register_error_handlers,
    )
    from security import register_security_headers  # security headers
    from ratelimit import init_rate_limiter        # rate limiting
    from schemas import ChatRequest, ChatResponse, ErrorResponse  # DTOs
    from services.openai_client import OpenAIService              # service façade
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
    from .schemas import ChatRequest, ChatResponse, ErrorResponse
    from .services.openai_client import OpenAIService
# ------------------------------------------------------------------------------------------------

load_dotenv()

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


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200  # for Render health checks

# --------------------------- API ROUTES -----------------------------------
@app.route("/api/chat", methods=["POST"])
def chat():
    """
    Non-streaming chat endpoint.
    Uses Pydantic DTOs for validation and OpenAIService for calls.
    """
    data = request.get_json(silent=True)
    if not data or "message" not in data:  # preserve original 400 for missing 'message'
        return jsonify({"error": "Missing JSON body or 'message' field"}), 400

    incoming_message = (data.get("message") or "").strip()  # trim for guardrail + DTO min_length
    model = data.get("model", "gpt-3.5-turbo")

    if len(incoming_message) > 4000:  # preserve 413 semantics
        return jsonify({"error": "Message too large"}), 413

    try:
        req = ChatRequest(message=incoming_message, model=model)  # DTO validation
    except ValidationError as ve:
        return jsonify({"error": ve.errors()}), 400  # concise validation response

    messages = [
        {"role": "system", "content": "You are a helpful assistant."},  # system prompt unchanged
        {"role": "user", "content": req.message},
    ]

    try:
        reply_text = openai_service.complete(model=req.model, messages=messages)
        resp = ChatResponse(reply=reply_text)
        return jsonify(resp.model_dump())
    except RuntimeError as exc:
        # Explicit handling for circuit breaker open
        if str(exc) == "circuit_open":
            current_app.logger.warning(
                "openai.circuit_open",
                extra={"event": "breaker.open", "request_id": getattr(g, "request_id", None)},
            )
            return jsonify({"error": "Service temporarily unavailable"}), 503
        # Otherwise generic 500 with previous error body shape
        current_app.logger.error(
            "openai.chat.error",
            exc_info=True,
            extra={
                "event": "openai.chat.error",
                "request_id": getattr(g, "request_id", None),
                "model": req.model,
            },
        )
        return jsonify({"error": str(exc)}), 500
    except Exception as e:
        # Log exception with request_id and return prior error shape
        current_app.logger.error(
            "openai.chat.error",
            exc_info=True,
            extra={
                "event": "openai.chat.error",
                "request_id": getattr(g, "request_id", None),
                "model": req.model,
            },
        )
        return jsonify({"error": str(e)}), 500


@app.route("/api/chat/stream", methods=["POST"])
def chat_stream():
    """
    Stream assistant tokens via Server-Sent Events (SSE).
    Validates via DTOs and streams via OpenAIService.
    """
    data = request.get_json(silent=True)
    if not data or "message" not in data:  # preserve original 400 for missing 'message'
        return jsonify({"error": "Missing JSON body or 'message' field"}), 400

    incoming_message = (data.get("message") or "").strip()
    model = data.get("model", "gpt-3.5-turbo")

    if len(incoming_message) > 4000:
        return jsonify({"error": "Message too large"}), 413

    try:
        req = ChatRequest(message=incoming_message, model=model)  # DTO validation
    except ValidationError as ve:
        return jsonify({"error": ve.errors()}), 400

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
        try:
            # Emit an initial event with the request_id for client correlation
            init_payload = {"request_id": getattr(g, "request_id", None)}
            yield f"data: {json.dumps(init_payload)}\n\n"  # initial SSE message

            # Stream tokens
            for token in openai_service.stream(model=req.model, messages=messages):
                payload = {"token": token}
                yield f"data: {json.dumps(payload)}\n\n"

            # Final done marker
            yield f"data: {json.dumps({'done': True})}\n\n"

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
            # Circuit breaker surfaced as a terminal event
            if str(exc) == "circuit_open":
                current_app.logger.warning(
                    "openai.circuit_open",
                    extra={
                        "event": "breaker.open",
                        "request_id": getattr(g, "request_id", None),
                        "model": req.model,
                    },
                )
                yield f"data: {json.dumps({'error': 'Service temporarily unavailable', 'done': True})}\n\n"
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
            yield f"data: {json.dumps({'error': str(exc), 'done': True})}\n\n"
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
            yield f"data: {json.dumps({'error': str(e), 'done': True})}\n\n"

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
