# server/ratelimit.py
# Minimal, app-scoped rate limiting with JSON 429 errors

from flask import jsonify, g, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_limiter.errors import RateLimitExceeded  # [CHANGED] v3: use Flask error handler


def init_rate_limiter(app) -> Limiter:
    """
    Initialize Flask-Limiter with a safe default and add a specific limit
    for /api/chat. Called after routes are registered.
    """
    if app.config.get("_RATE_LIMITER_INIT", False):
        limiter = app.extensions.get("limiter")
        if limiter:
            return limiter  # type: ignore

    limiter = Limiter(
        key_func=get_remote_address,
        app=app,
        default_limits=["300/minute"],     # [CHANGED] consistent v3 style "N/unit"
        storage_uri="memory://",           # simple in-memory store (Render dyno)
        headers_enabled=True,              # send standard rate-limit headers
    )

    @limiter.request_filter
    def _health_skip():
        # Don’t rate-limit health checks
        return request.path == "/health"

    # [CHANGED] v3: register a Flask error handler instead of limiter.error_handler
    @app.errorhandler(RateLimitExceeded)
    def _rate_limit_exceeded(e):
        payload = {
            "error": "Too Many Requests",
            "code": 429,
            "request_id": getattr(g, "request_id", None),
        }
        return jsonify(payload), 429

    # Apply a stricter limit to the chat endpoint if present
    chat_view = app.view_functions.get("chat")
    if chat_view is not None:
        limiter.limit("60/minute")(chat_view)  # [UNCHANGED] per-route limit

    # Expose for reuse/tests
    app.extensions["limiter"] = limiter
    app.config["_RATE_LIMITER_INIT"] = True
    return limiter
