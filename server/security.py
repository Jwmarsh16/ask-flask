# server/security.py
# Sets common security headers (CSP, HSTS, X-Content-Type-Options, Referrer-Policy, X-Frame-Options)


def register_security_headers(app) -> None:
    """Attach common security headers on all responses."""
    if app.config.get("_SEC_HEADERS_INIT", False):
        return  # idempotent for reloader

    @app.after_request
    def _security_headers(resp):
        # Content Security Policy - tuned to typical Vite builds
        # Adjust if you add external CDNs or inline scripts.
        csp = (
            "default-src 'self'; "
            "img-src 'self' data: blob:; "
            "style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; "
            "font-src 'self' data:; "
            "connect-src 'self'; "
            "base-uri 'self'; "
            "frame-ancestors 'none'"
        )
        resp.headers.setdefault("Content-Security-Policy", csp)

        # HSTS (only relevant over HTTPS; harmless if http during local dev)
        resp.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains; preload"
        )

        # MIME sniffing protection
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")

        # Privacy
        resp.headers.setdefault("Referrer-Policy", "no-referrer")

        # Clickjacking protection
        resp.headers.setdefault("X-Frame-Options", "DENY")

        # Permissions Policy (tighten as needed)
        resp.headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
        )

        return resp

    app.config["_SEC_HEADERS_INIT"] = True
