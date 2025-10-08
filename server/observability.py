# server/observability.py
# Cross-cutting concerns: JSON logging, request IDs, latency logging, error JSON for /api/*

import sys
import time
import logging
from uuid import uuid4
from typing import Any, Dict

from flask import g, request, jsonify
from werkzeug.exceptions import HTTPException
from pydantic import ValidationError  # <-- CHANGED: explicitly handle DTO errors

try:
    from pythonjsonlogger import jsonlogger
except Exception:  # pragma: no cover
    jsonlogger = None  # fallback to plain logs if missing


def _json_formatter() -> logging.Formatter:
    if jsonlogger is None:
        return logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    return jsonlogger.JsonFormatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s "
        "%(request_id)s %(method)s %(path)s %(status)s %(latency_ms)s "
        "%(remote_ip)s %(user_agent)s %(event)s %(model)s "
        "%(prompt_tokens)s %(completion_tokens)s %(total_tokens)s"
    )


def init_logging(app) -> None:
    if app.config.get("_OBS_LOGGING_INIT", False):
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_json_formatter())
    app.logger.handlers.clear()
    app.logger.addHandler(handler)
    app.logger.setLevel(logging.INFO)
    app.logger.propagate = False
    app.config["_OBS_LOGGING_INIT"] = True


def register_request_id(app) -> None:
    if app.config.get("_OBS_REQID_INIT", False):
        return

    @app.before_request
    def _before_request():
        g.request_id = str(uuid4())
        g._start_time = time.monotonic()

    @app.after_request
    def _after_request(resp):
        resp.headers["X-Request-ID"] = getattr(g, "request_id", "")
        return resp

    app.config["_OBS_REQID_INIT"] = True


def register_latency_logging(app) -> None:
    if app.config.get("_OBS_LATENCY_INIT", False):
        return

    @app.after_request
    def _access_log(resp):
        try:
            start = getattr(g, "_start_time", None)
            latency_ms = int((time.monotonic() - start) * 1000) if start else None
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
            pass
        return resp

    app.config["_OBS_LATENCY_INIT"] = True


def register_error_handlers(app) -> None:
    if app.config.get("_OBS_ERRORS_INIT", False):
        return

    @app.errorhandler(ValidationError)  # <-- CHANGED: pydantic DTO errors to unified 400
    def _validation_error(e: ValidationError):
        if not request.path.startswith("/api"):
            return e
        payload = {
            "error": "Validation error",
            "code": 400,
            "request_id": getattr(g, "request_id", None),
            "details": e.errors(),
        }
        app.logger.warning("http.error", extra={"event": "http.error", **payload})
        return jsonify(payload), 400

    @app.errorhandler(HTTPException)
    def _http_exception(e: HTTPException):
        if not request.path.startswith("/api"):
            return e
        payload = {
            "error": e.description or e.name,
            "code": e.code,
            "request_id": getattr(g, "request_id", None),
        }
        app.logger.warning("http.error", extra={"event": "http.error", **payload})
        return jsonify(payload), e.code

    @app.errorhandler(Exception)
    def _unhandled_exception(e: Exception):
        if not request.path.startswith("/api"):
            return e
        payload = {
            "error": "Internal Server Error",
            "code": 500,
            "request_id": getattr(g, "request_id", None),
        }
        app.logger.error("http.exception", exc_info=True, extra={"event": "http.exception", **payload})
        return jsonify(payload), 500

    app.config["_OBS_ERRORS_INIT"] = True
