# server/ratelimit.py
# Minimal, app-scoped rate limiting with JSON 429 errors

from flask import jsonify, g, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address


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
        default_limits=["300 per minute"],  # global safety net
        storage_uri="memory://",            # simple in-memory store (Render dyno)
        headers_enabled=True,               # send standard rate-limit headers
    )

    @limiter.request_filter
    def _health_skip():
        return request.path == "/health"  # don’t rate-limit health checks

    @limiter.error_handler
    def _rate_limit_exceeded(e):
        payload = {
            "error": "Too Many Requests",
            "code": 429,
            "request_id": getattr(g, "request_id", None),
        }
        return jsonify(payload), 429

    chat_view = app.view_functions.get("chat")
    if chat_view is not None:
        limiter.limit("60 per minute")(chat_view)

    app.extensions["limiter"] = limiter
    app.config["_RATE_LIMITER_INIT"] = True
    return limiter
