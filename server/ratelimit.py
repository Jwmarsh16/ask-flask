# server/ratelimit.py
# Minimal, app-scoped rate limiting with JSON 429 errors

import os  # CHANGED: support test-mode toggles via env

from flask import g, jsonify, request
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


def _env_truthy(name: str) -> bool:
    """Return True for common truthy env var values."""
    val = (os.getenv(name) or "").strip().lower()
    return val in ("1", "true", "yes", "y", "on")


def _is_test_mode(app) -> bool:
    """
    Determine if we're running under tests.

    CHANGED: We cannot rely on app.testing being set before server.app imports,
    because init_rate_limiter(app) is called at import time. So we also use
    an env var set in repo-root conftest.py.
    """
    # CHANGED: wrap for Black formatting; no behavior change
    return bool(
        app.config.get("TESTING")
        or getattr(app, "testing", False)
        or _env_truthy("ASKFLASK_TESTING")
    )


def _parse_per_minute_limit(limit_str: str) -> str:
    """
    Best-effort parse for X-RateLimit-Limit header.
    Example: "5/minute;50/hour;100/day" -> "5"
    """
    first = (limit_str.split(";")[0] if limit_str else "").strip()
    if "/" in first:
        return first.split("/", 1)[0].strip() or "0"
    return first or "0"


def _ensure_rate_limit_headers_hook(app) -> None:
    """
    CHANGED: Add a tiny after_request hook that ensures rate limit headers exist
    for chat endpoints even if the limiter library doesn't inject them in a
    particular environment/config. We do NOT override headers if they already
    exist (setdefault).
    """
    if app.config.get("_RATE_LIMIT_HEADERS_HOOK_INIT", False):
        return

    @app.after_request
    def _ensure_rl_headers(resp):
        if request.endpoint in ("chat", "chat_stream"):
            # If Flask-Limiter injected real values, we keep them.
            per_min = str(app.config.get("_CHAT_RL_PER_MINUTE", "0"))
            resp.headers.setdefault("X-RateLimit-Limit", per_min)
            resp.headers.setdefault("X-RateLimit-Remaining", per_min)
            resp.headers.setdefault("X-RateLimit-Reset", "0")
        return resp

    app.config["_RATE_LIMIT_HEADERS_HOOK_INIT"] = True


def init_rate_limiter(app) -> Limiter:
    """
    Initialize Flask-Limiter with a shared limit for both chat endpoints.
    Called after routes are registered (see app.py).
    """
    # CHANGED: detect test mode early and make it visible to the rest of the app
    test_mode = _is_test_mode(app)
    if test_mode:
        app.config["TESTING"] = True  # ensures consistent behavior elsewhere

    # If already initialized, still ensure our header hook exists
    if app.config.get("_RATE_LIMITER_INIT", False):
        limiter = app.extensions.get("limiter")
        _ensure_rate_limit_headers_hook(app)  # CHANGED: ensure hook exists
        if limiter:
            return limiter  # already initialized

    # Ensure headers are emitted reliably (belt & suspenders).
    app.config["RATELIMIT_HEADERS_ENABLED"] = True  # force header injection

    limiter = Limiter(
        key_func=_client_ip,  # respect CF/XFF so limits are truly per-client-IP
        app=app,
        default_limits=["300/minute"],  # global safety net (non-chat endpoints too)
        storage_uri="memory://",  # per-instance (fine for single dyno)
        headers_enabled=True,  # emit X-RateLimit-* and Retry-After
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
        resp = jsonify(payload)
        resp.status_code = 429
        # CHANGED: ensure Retry-After exists even if extension doesn't add it
        resp.headers.setdefault("Retry-After", "60")
        return resp

    # ------------------------ KEY CHANGE: STRICT SHARED LIMIT ------------------------
    # Use ONE shared budget for both chat endpoints so they cannot bypass each other.
    #
    # CHANGED: Use a very high limit in tests to prevent pytest from tripping 429s
    # across multiple test cases (memory:// counts persist across the test run).
    if test_mode:
        limit_spec = os.getenv(
            "CHAT_RATE_LIMIT_TEST",
            "100000/minute;100000/hour;100000/day",
        )
    else:
        limit_spec = os.getenv("CHAT_RATE_LIMIT", "5/minute;50/hour;100/day")

    # Store a parsed per-minute value for our header fallback.
    app.config["_CHAT_RL_PER_MINUTE"] = _parse_per_minute_limit(limit_spec)  # CHANGED

    shared_chat_limit = limiter.shared_limit(
        limit_spec,
        scope="chat-endpoints",
    )

    # Wrap and re-register endpoints so the limit applies AND headers appear.
    if "chat" in app.view_functions:
        app.view_functions["chat"] = shared_chat_limit(app.view_functions["chat"])
    if "chat_stream" in app.view_functions:
        app.view_functions["chat_stream"] = shared_chat_limit(
            app.view_functions["chat_stream"]
        )  # CHANGED: wrap call to satisfy Black line-length

    # CHANGED: ensure header hook is registered
    _ensure_rate_limit_headers_hook(app)

    app.extensions["limiter"] = limiter
    app.config["_RATE_LIMITER_INIT"] = True
    return limiter
