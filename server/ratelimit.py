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
    ip = request.headers.get("CF-Connecting-IP")  # prefer CF header for real client IP
    if ip:
        return ip.strip()
    xff = request.headers.get("X-Forwarded-For")  # then first XFF hop
    if xff:
        return xff.split(",")[0].strip()
    return get_remote_address()  # unchanged fallback to Werkzeug's remote addr


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
    app.config["RATELIMIT_HEADERS_ENABLED"] = True  # force header injection

    limiter = Limiter(
        key_func=_client_ip,          # respect CF/XFF so limits are truly per-client-IP
        app=app,
        default_limits=["300/minute"],  # global safety net (non-chat endpoints too)
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
        return jsonify(payload), 429  # unified JSON error shape for 429s

    # ------------------------ KEY CHANGE: STRICT SHARED LIMIT ------------------------
    # Use ONE shared budget for both chat endpoints so they cannot bypass each other.
    # This protects your OpenAI bill while still allowing a reasonable demo:
    # - 5 requests per minute
    # - 50 requests per hour
    # - 100 requests per day
    shared_chat_limit = limiter.shared_limit(
        "5/minute;50/hour;100/day",  # stricter per-IP budget for OpenAI-backed chat
        scope="chat-endpoints",
    )

    # Wrap and re-register endpoints so the limit applies AND headers appear.
    if "chat" in app.view_functions:
        app.view_functions["chat"] = shared_chat_limit(app.view_functions["chat"])  # wrap /api/chat
    if "chat_stream" in app.view_functions:
        app.view_functions["chat_stream"] = shared_chat_limit(app.view_functions["chat_stream"])  # wrap /api/chat/stream

    # NOTE: We intentionally do NOT also apply per-route limits here to avoid
    # double-counting or confusing headers. The shared limit is the source of truth.

    app.extensions["limiter"] = limiter
    app.config["_RATE_LIMITER_INIT"] = True
    return limiter
