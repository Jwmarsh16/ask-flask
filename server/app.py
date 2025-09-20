# server/app.py
# Flask serves ../client/dist and exposes /api routes

from config import app  # existing Flask app instance
import os
import logging  # [NEW] structured logging uses app.logger
from openai import OpenAI
from flask import (
    request,
    jsonify,
    render_template,  # ← render_template for SPA fallback
    current_app,      # [NEW] for proper logger access inside requests
    g,                # [NEW] to attach request_id and timing
)
from dotenv import load_dotenv

# [NEW] Observability & security modules (Track 1 minimal integration)
from observability import (  # type: ignore
    init_logging,                 # JSON logging formatter
    register_request_id,          # X-Request-ID + g.request_id
    register_latency_logging,     # one structured access log per request
    register_error_handlers,      # JSON errors for /api/*
)
from security import register_security_headers  # type: ignore
# NOTE: rate limiter must be initialized AFTER routes are bound
from ratelimit import init_rate_limiter  # type: ignore

load_dotenv()

# [CHANGED] Add conservative retries + timeout for robustness
client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    max_retries=2,     # retry transient failures a couple times
    timeout=30.0,      # hard deadline per request (seconds)
)

# ---------------------- BOOTSTRAP CROSS-CUTTING CONCERNS ------------------
# [NEW] Initialize structured JSON logging & middleware
init_logging(app)                 # set JSON formatter on Flask logger
register_request_id(app)          # attach g.request_id and X-Request-ID
register_latency_logging(app)     # log method/path/status/latency_ms
register_error_handlers(app)      # consistent JSON errors for /api/*
register_security_headers(app)    # set CSP/HSTS/X-Content-Type/Referrer headers
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

    user_message = (data.get('message') or '').strip()  # [CHANGED] trim whitespace
    model = data.get('model', 'gpt-3.5-turbo')  # default model

    # [NEW] Guardrail: reject unreasonably large inputs to protect the service
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

        # [NEW] Emit a structured usage/latency log for observability
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
            # Never let logging failures affect the response
            pass  # no-op; safety in case usage fields are absent

        return jsonify({'reply': reply})
    except Exception as e:
        # [NEW] Log the exception with the same request_id for correlation
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
# -------------------------------------------------------------------------

# ---------------------- SPA FALLBACK FOR ROUTING -------------------------
# Any non-API 404 returns the built index.html so client-side routes work.
@app.errorhandler(404)
def not_found(_e):
    # NOTE: Our global error handlers in observability.py intentionally
    # skip non-/api paths so this SPA fallback still works.
    return render_template("index.html")
# -------------------------------------------------------------------------

# [NEW] Initialize rate limiter *after* routes are registered
init_rate_limiter(app)  # attach global + per-route (/api/chat) limits

if __name__ == '__main__':
    # Local dev convenience; Render will use gunicorn
    # NOTE: Flask reloader can double-register handlers; our modules
    # are written to be idempotent to minimize duplicate registration.
    app.run(debug=True)
