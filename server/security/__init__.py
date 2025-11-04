# server/security/__init__.py
# Purpose: Provide `register_security_headers(app)` from the `security` package
# so imports like `from security import register_security_headers` keep working.
# This avoids the module/package name collision introduced by adding
# `server/security/pii_redaction.py`.

from typing import Any
from flask import Response

def register_security_headers(app: Any) -> None:
    """Attach strict security headers to every response.  # add function expected by app.py
    Mirrors the intent of the previous security module without extra deps."""
    @app.after_request
    def _set_headers(resp: Response) -> Response:
        # CSP: self-only; allow data: for inline images (e.g., copy buttons)  # explain CSP
        csp = (
            "default-src 'self'; "
            "img-src 'self' data:; "
            "style-src 'self'; "
            "script-src 'self'; "
            "connect-src 'self'; "     # XHR/fetch/SSE to same origin
            "frame-ancestors 'none'"
        )
        resp.headers.setdefault("Content-Security-Policy", csp)          # add CSP
        resp.headers.setdefault("Referrer-Policy", "no-referrer")        # tighten referrers
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")     # prevent MIME sniffing
        resp.headers.setdefault("X-Frame-Options", "DENY")               # clickjacking protection
        resp.headers.setdefault(
            "Permissions-Policy",
            "geolocation=(), microphone=(), camera=()"                   # disable sensitive APIs by default
        )
        # HSTS only makes sense over HTTPS; Render prod is HTTPS-terminated.  # explain HSTS condition
        if app.config.get("PREFERRED_URL_SCHEME", "https") == "https":
            resp.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=63072000; includeSubDomains; preload"           # 2 years HSTS
            )
        return resp
