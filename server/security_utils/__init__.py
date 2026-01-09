# server/security_utils/__init__.py
# Re-export helpers for simple imports like: from server.security_utils import redact

from .pii_redaction import detect, redact  # CHANGED: drop redundant "as detect/redact"

__all__ = [detect.__name__, redact.__name__]  # CHANGED: reference names to satisfy F401
