# server/observability.py
# Cross-cutting concerns: JSON logging, request IDs, latency logging, error JSON for /api/*

import sys
import time
import logging
from uuid import uuid4
from typing import Any, Dict

from flask import g, request, jsonify
from werkzeug.exceptions import HTTPException

try:
    from pythonjsonlogger import jsonlogger
except Exception:  # pragma: no cover
    jsonlogger = None  # graceful fallback; plain logs if missing


def _json_formatter() -> logging.Formatter:
    """Create a JSON formatter for logs."""
    if jsonlogger is None:
        # Fallback to plain text if dependency missing
        return logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")

    fmt = jsonlogger.JsonFormatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s "
        "%(request_id)s %(method)s %(path)s %(status)s %(latency_ms)s "
        "%(remote_ip)s %(user_agent)s %(event)s %(model)s "
        "%(prompt_tokens)s %(completion_tokens)s %(total_tokens)s"
    )
    return fmt


def init_logging(app) -> None:
    """Configure Flask's logger to emit JSON to stdout."""
    if app.config.get("_OBS_LOGGING_INIT", False):
        return  # idempotency for reloader

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_json_formatter())

    # Configure app logger
    app.logger.handlers.clear()
    app.logger.addHandler(handler)
    app.logger.setLevel(logging.INFO)
    app.logger.propagate = False

    app.config["_OBS_LOGGING_INIT"] = True


def register_request_id(app) -> None:
    """Attach a unique request_id and start time to each request; add response header."""
    if app.config.get("_OBS_REQID_INIT", False):
        return

    @app.before_request
    def _before_request():
        g.request_id = str(uuid4())
        g._start_time = time.monotonic()

    @app.after_request
    def _after_request(resp):
        # Add X-Request-ID for client-side correlation
        try:
            resp.headers["X-Request-ID"] = getattr(g, "request_id", "")
        except Exception:
            pass
        return resp

    app.config["_OBS_REQID_INIT"] = True


def register_latency_logging(app) -> None:
    """Log one structured line per request with method/path/status/latency."""
    if app.config.get("_OBS_LATENCY_INIT", False):
        return

    @app.after_request
    def _access_log(resp):
        try:
            start = getattr(g, "_start_time", None)
            latency_ms = None
            if start is not None:
                latency_ms = int((time.monotonic() - start) * 1000)

            record: Dict[str, Any] = {
                "request_id": getattr(g, "request_id", None),
                "method": request.method,
                "path": request.path,
                "status": resp.status_code,
                "latency_ms": latency_ms,
                "remote_ip": request.headers.get("X-Forwarded-For", request.remote_addr),
                "user_agent": request.user_agent.string if request.user_agent else None,
                "event": "http.access",
            }
            app.logger.info("http.access", extra=record)
        except Exception:
            # Never let logging break responses
            pass
        return resp

    app.config["_OBS_LATENCY_INIT"] = True


def register_error_handlers(app) -> None:
    """Return JSON errors for API routes while preserving SPA fallback for non-API."""
    if app.config.get("_OBS_ERRORS_INIT", False):
        return

    @app.errorhandler(HTTPException)
    def _http_exception(e: HTTPException):
        # Keep non-API behavior (e.g., SPA 404) intact
        if not request.path.startswith("/api"):
            return e
        payload = {
            "error": e.description or e.name,
            "code": e.code,
            "request_id": getattr(g, "request_id", None),
        }
        # Log with stack=False for HTTP errors
        app.logger.warning("http.error", extra={"event": "http.error", **payload})
        return jsonify(payload), e.code

    @app.errorhandler(Exception)
    def _unhandled_exception(e: Exception):
        # Preserve non-API error pages (e.g., static/HTML) for non-API paths
        if not request.path.startswith("/api"):
            return e
        payload = {
            "error": "Internal Server Error",
            "code": 500,
            "request_id": getattr(g, "request_id", None),
        }
        # Log with stack trace for server errors
        app.logger.error("http.exception", exc_info=True, extra={"event": "http.exception", **payload})
        return jsonify(payload), 500

    app.config["_OBS_ERRORS_INIT"] = True
