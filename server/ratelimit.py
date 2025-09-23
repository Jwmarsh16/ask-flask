# server/ratelimit.py
# Minimal, app-scoped rate limiting with JSON 429 errors

from flask import jsonify, g, request
from flask_limiter import Limiter
from flask_limiter.errors import RateLimitExceeded  # v3: use Flask error handler
from flask_limiter.util import get_remote_address


def _client_ip():
    """
    Prefer edge-provided IPs when behind a proxy/CDN (Cloudflare on Render).
    Falls back to Werkzeug's remote_addr via get_remote_address().
    """
    ip = request.headers.get("CF-Connecting-IP")  # <-- CHANGED: prefer CF header
    if ip:
        return ip.strip()
    xff = request.headers.get("X-Forwarded-For")  # <-- CHANGED: then first XFF hop
    if xff:
        return xff.split(",")[0].strip()
    return get_remote_address()  # <-- unchanged fallback


def init_rate_limiter(app) -> Limiter:
    """
    Initialize Flask-Limiter with a shared limit for both chat endpoints.
    Called after routes are registered (see app.py).
    """
    if app.config.get("_RATE_LIMITER_INIT", False):
        limiter = app.extensions.get("limiter")
        if limiter:
            return limiter  # already initialized

    # Ensure headers are emitted reliably (belt & suspenders).
    app.config["RATELIMIT_HEADERS_ENABLED"] = True  # <-- ADDED: force header injection

    limiter = Limiter(
        key_func=_client_ip,          # <-- CHANGED: respect CF/XFF for per-IP limits
        app=app,
        default_limits=["300/minute"],  # global safety net (unchanged)
        storage_uri="memory://",        # per-instance (fine for single dyno)
        headers_enabled=True,           # emit X-RateLimit-* and Retry-After
    )

    @limiter.request_filter
    def _health_skip():
        return request.path == "/health"  # don’t rate-limit health checks

    # v3: register a Flask error handler instead of limiter.error_handler
    @app.errorhandler(RateLimitExceeded)
    def _rate_limit_exceeded(_e):
        payload = {
            "error": "Too Many Requests",
            "code": 429,
            "request_id": getattr(g, "request_id", None),
        }
        return jsonify(payload), 429

    # ------------------------ KEY FIX: SHARED LIMIT ------------------------
    # Use ONE shared budget (15/min) for both chat endpoints so they cannot
    # bypass each other by switching routes.
    shared_chat_limit = limiter.shared_limit("15/minute", scope="chat-endpoints")  # <-- ADDED

    # Wrap and re-register endpoints so the limit applies AND headers appear.
    if "chat" in app.view_functions:
        app.view_functions["chat"] = shared_chat_limit(app.view_functions["chat"])           # <-- CHANGED: assign wrapped view
    if "chat_stream" in app.view_functions:
        app.view_functions["chat_stream"] = shared_chat_limit(app.view_functions["chat_stream"])  # <-- ADDED

    # NOTE: We intentionally do NOT also apply per-route limits here to avoid
    # double-counting or confusing headers. The shared limit is the source of truth.

    app.extensions["limiter"] = limiter
    app.config["_RATE_LIMITER_INIT"] = True
    return limiter
