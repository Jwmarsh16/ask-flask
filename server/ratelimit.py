# server/ratelimit.py
# Minimal, app-scoped rate limiting with JSON 429 errors

from flask import jsonify, g, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_limiter.errors import RateLimitExceeded  # v3: use Flask error handler

def _client_ip():
    """
    Prefer edge-provided IPs when behind a proxy/CDN.
    Falls back to Werkzeug's remote_addr.
    """
    # Prefer Cloudflare's header if present
    ip = request.headers.get("CF-Connecting-IP")
    if ip:
        return ip.strip()
    # Fallback to the first X-Forwarded-For hop
    xff = request.headers.get("X-Forwarded-For")
    if xff:
        return xff.split(",")[0].strip()
    # Fallback to Werkzeug's remote_addr
    return get_remote_address()

def init_rate_limiter(app) -> Limiter:
    """
    Initialize Flask-Limiter with a safe default and add a specific limit
    for /api/chat and /api/chat/stream. Called after routes are registered.
    """
    if app.config.get("_RATE_LIMITER_INIT", False):
        limiter = app.extensions.get("limiter")
        if limiter:
            return limiter  # already initialized

    # Ensure headers are emitted (belt & suspenders alongside constructor flag)
    app.config["RATELIMIT_HEADERS_ENABLED"] = True  # <-- ADDED: force header injection

    limiter = Limiter(
        key_func=_client_ip,         # <-- CHANGED: respect CF/XFF for per-IP limits
        app=app,
        default_limits=["300/minute"],  # global safety net (unchanged)
        storage_uri="memory://",        # simple in-memory store (per instance)
        headers_enabled=True,           # emit X-RateLimit-* and Retry-After
    )

    @limiter.request_filter
    def _health_skip():
        return request.path == "/health"   # don’t rate-limit health checks

    # v3: register a Flask error handler instead of limiter.error_handler
    @app.errorhandler(RateLimitExceeded)
    def _rate_limit_exceeded(_e):
        payload = {
            "error": "Too Many Requests",
            "code": 429,
            "request_id": getattr(g, "request_id", None),
        }
        return jsonify(payload), 429

    # IMPORTANT: Wrap and re-register view functions so per-route limits apply
    # Without assigning back, some setups won't inject headers or enforce per-route limits.
    if "chat" in app.view_functions:
        app.view_functions["chat"] = limiter.limit("15/minute")(app.view_functions["chat"])  # <-- CHANGED: assign wrapped view

    if "chat_stream" in app.view_functions:
        app.view_functions["chat_stream"] = limiter.limit("15/minute")(app.view_functions["chat_stream"])  # <-- ADDED: limit SSE route

    app.extensions["limiter"] = limiter
    app.config["_RATE_LIMITER_INIT"] = True
    return limiter
