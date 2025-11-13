# server/security_utils/pii_redaction.py
# Demo-grade PII detect+redact for pre-index and pre-prompt; upgrade to Presidio later.

import re

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")  # email pattern
PHONE_RE = re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")  # US phone
SSN_RE   = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")  # SSN (demo)
CC_RE    = re.compile(r"\b(?:\d[ -]*?){13,19}\b")  # naive CC detector (false positives possible)

def detect(text: str) -> dict:
    """Return simple PII matches (demo only; false positives possible)."""
    return {
        "emails": EMAIL_RE.findall(text),
        "phones": PHONE_RE.findall(text),
        "ssns":   SSN_RE.findall(text),
        "cards":  [m.group(0) for m in CC_RE.finditer(text)],
    }

def redact(text: str, mask: str = "[REDACTED]") -> str:
    """Replace matched PII with a mask string."""
    for rex in (EMAIL_RE, PHONE_RE, SSN_RE, CC_RE):
        text = rex.sub(mask, text)
    return text
