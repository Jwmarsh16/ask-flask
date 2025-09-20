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
    Response,         # <-- ADDED: for streaming responses
    stream_with_context,  # <-- ADDED: keep Flask ctx during generator
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
except ImportError:
    from observability import (
        init_logging,
        register_request_id,
        register_latency_logging,
        register_error_handlers,
    )
    from security import register_security_headers
    from ratelimit import init_rate_limiter

load_dotenv()

# Robust OpenAI client: retries + timeout
client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    max_retries=2,     # retry transient failures a couple times
    timeout=30.0,      # hard deadline per request (seconds)
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
@app.route('/api/chat', methods=['POST'])
def chat():
    data = request.get_json(silent=True)
    if not data or "message" not in data:
        return jsonify({"error": "Missing JSON body or 'message' field"}), 400  # validation

    user_message = (data.get('message') or '').strip()  # trim whitespace
    model = data.get('model', 'gpt-3.5-turbo')  # default model

    # Guardrail: reject unreasonably large inputs to protect the service
    if len(user_message) > 4000:  # ~4KB text limit (tunable)
        return jsonify({"error": "Message too large"}), 413

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": user_message}
            ],
        )

        reply = response.choices[0].message.content

        # Structured usage log for observability (token counts)
        try:
            usage = getattr(response, "usage", None)
            prompt_tokens = getattr(usage, "prompt_tokens", None)
            completion_tokens = getattr(usage, "completion_tokens", None)
            total_tokens = getattr(usage, "total_tokens", None)
            current_app.logger.info(
                "openai.chat.complete",
                extra={
                    "event": "openai.chat.complete",
                    "request_id": getattr(g, "request_id", None),
                    "model": model,
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": total_tokens,
                },
            )
        except Exception:
            pass  # never let logging failures affect the response

        return jsonify({'reply': reply})
    except Exception as e:
        # Log exception with the same request_id for correlation
        current_app.logger.error(
            "openai.chat.error",
            exc_info=True,
            extra={
                "event": "openai.chat.error",
                "request_id": getattr(g, "request_id", None),
                "model": model,
            },
        )
        return jsonify({'error': str(e)}), 500


@app.route('/api/chat/stream', methods=['POST'])
def chat_stream():
    """
    Stream assistant tokens via Server-Sent Events (SSE).
    Keeps existing /api/chat unchanged for graceful fallback.
    """
    data = request.get_json(silent=True)
    if not data or "message" not in data:
        return jsonify({"error": "Missing JSON body or 'message' field"}), 400  # validation

    user_message = (data.get('message') or '').strip()
    model = data.get('model', 'gpt-3.5-turbo')

    # Same guardrail as non-stream route
    if len(user_message) > 4000:
        return jsonify({"error": "Message too large"}), 413

    # Log stream start for correlation
    current_app.logger.info(
        "openai.chat.stream.start",
        extra={
            "event": "openai.chat.stream.start",  # <-- ADDED: start log
            "request_id": getattr(g, "request_id", None),
            "model": model,
        },
    )

    @stream_with_context  # <-- ADDED: ensure g.request_id etc. remain available
    def generate():
        import json
        try:
            # Start the OpenAI streaming request
            stream = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": user_message},
                ],
                stream=True,  # <-- ADDED: enable streaming
            )

            # Emit an initial event with the request_id for client correlation (optional)
            init_payload = {"request_id": getattr(g, "request_id", None)}
            yield f"data: {json.dumps(init_payload)}\n\n"  # <-- ADDED: initial SSE message

            # Iterate chunks and push deltas as tokens
            for chunk in stream:
                try:
                    # The SDK yields ChatCompletionChunk objects; extract the delta content if present
                    delta = chunk.choices[0].delta
                    token = getattr(delta, "content", None)
                    if token:
                        payload = {"token": token}
                        yield f"data: {json.dumps(payload)}\n\n"  # <-- ADDED: per-token SSE
                except Exception:
                    # If the shape changes, best-effort emit raw chunk
                    payload = {"token": str(chunk)}
                    yield f"data: {json.dumps(payload)}\n\n"

            # Final event to signal completion
            done_payload = {"done": True}
            yield f"data: {json.dumps(done_payload)}\n\n"  # <-- ADDED: done marker

            # Log completion (usage may not be available on streamed chunks)
            current_app.logger.info(
                "openai.chat.stream.complete",
                extra={
                    "event": "openai.chat.stream.complete",  # <-- ADDED: end log
                    "request_id": getattr(g, "request_id", None),
                    "model": model,
                    # Tokens unknown in most streamed cases; leave None to avoid wrong data.
                    "prompt_tokens": None,
                    "completion_tokens": None,
                    "total_tokens": None,
                },
            )
        except Exception as e:
            # Log and surface a terminal SSE error event (response is already streaming)
            current_app.logger.error(
                "openai.chat.stream.error",
                exc_info=True,
                extra={
                    "event": "openai.chat.stream.error",  # <-- ADDED: error log
                    "request_id": getattr(g, "request_id", None),
                    "model": model,
                },
            )
            err_payload = {"error": str(e), "done": True}
            yield f"data: {json.dumps(err_payload)}\n\n"

    # Stream-friendly headers (avoid proxy buffering)
    headers = {
        "Cache-Control": "no-cache",          # <-- ADDED: prevent caching
        "X-Accel-Buffering": "no",            # <-- ADDED: disable buffering on some proxies
        "Connection": "keep-alive",           # <-- ADDED: keep connection open
    }
    return Response(generate(), mimetype="text/event-stream", headers=headers)  # <-- ADDED: SSE Response
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

if __name__ == '__main__':
    # Local dev convenience; Render uses gunicorn
    app.run(debug=True)
