# server/services/session_store.py
# Service/repository layer for Session & Message operations.
# This isolates DB logic from Flask routes. Routes can call these
# functions directly (JSON/DTO mapping done at the edge).

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, List, Tuple, Optional

# --- Mode-aware imports (supports both launch modes: top-level vs package) ---
try:
    # Package mode: gunicorn server.app:app
    from ..config import db  # type: ignore
    from ..models import Session, Message  # type: ignore
except Exception:  # noqa: BLE001
    # Top-level mode: gunicorn --chdir server app:app
    from config import db  # type: ignore
    from models import Session, Message  # type: ignore
# -----------------------------------------------------------------------------

# SQLAlchemy helpers from the Flask-SQLAlchemy facade
from sqlalchemy import text  # for order_by("... DESC") safely


def _utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Normalize to aware UTC datetimes for consistent JSON output."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ------------------------------ Public API ----------------------------------


def create_session(title: Optional[str] = None) -> Session:
    s = Session(title=title)               # create row
    db.session.add(s)                      # stage
    db.session.commit()                    # persist
    return s


def get_session(session_id: str) -> Optional[Session]:
    return db.session.get(Session, session_id)


def list_sessions() -> List[dict]:
    """
    Return session summaries:
      [{id, title, created_at, last_activity}], sorted by last_activity desc.
    last_activity = max(message.created_at) or session.created_at if no messages.
    """
    q = (
        db.session.query(
            Session.id,
            Session.title,
            Session.created_at,
            db.func.coalesce(db.func.max(Message.created_at), Session.created_at).label(
                "last_activity"
            ),
        )
        .outerjoin(Message, Message.session_id == Session.id)
        .group_by(Session.id, Session.title, Session.created_at)
        .order_by(text("last_activity DESC"))  # use sqlalchemy.text for clarity
    )

    rows = []
    for sid, title, created_at, last_activity in q:
        rows.append(
            {
                "id": sid,
                "title": title,
                "created_at": _utc(created_at),
                "last_activity": _utc(last_activity),
            }
        )
    return rows


def get_session_messages(session_id: str) -> List[dict]:
    msgs: Iterable[Message] = (
        db.session.query(Message)
        .filter(Message.session_id == session_id)
        .order_by(Message.created_at.asc())
        .all()
    )
    out: List[dict] = []
    for m in msgs:
        out.append(
            {
                "id": m.id,
                "role": str(m.role),
                "content": m.content,
                "tokens": m.tokens,
                "created_at": _utc(m.created_at),
            }
        )
    return out


def append_message(session_id: str, role: str, content: str, tokens: Optional[int] = None) -> Message:
    s = db.session.get(Session, session_id)
    if not s:
        raise ValueError("session_not_found")

    m = Message(session_id=session_id, role=role, content=content, tokens=tokens)
    db.session.add(m)

    # Touch parent updated_at (DB onupdate also handles this, but be explicit)
    s.updated_at = db.func.now()  # type: ignore[assignment]

    db.session.commit()
    return m


def rename_session(session_id: str, title: str) -> Session:  # <-- ADDED earlier: service to support PATCH /api/sessions/:id
    """
    Rename a session. Expects a validated, non-empty title (DTO enforces this).
    Updates updated_at; last_activity is computed from messages and not stored.
    """
    s = db.session.get(Session, session_id)
    if not s:
        raise ValueError("session_not_found")

    normalized = title.strip()  # defense-in-depth; DTO already trims
    s.title = normalized
    s.updated_at = db.func.now()  # explicitly bump updated_at

    db.session.commit()
    db.session.refresh(s)  # ensure timestamps reflect DB values
    return s


def delete_session(session_id: str) -> bool:
    s = db.session.get(Session, session_id)
    if not s:
        return False
    db.session.delete(s)
    db.session.commit()
    return True


def export_session(session_id: str, fmt: str) -> Tuple[str, bytes, str]:
    s = db.session.get(Session, session_id)
    if not s:
        raise ValueError("session_not_found")

    msgs = get_session_messages(session_id)

    payload = {
        "id": s.id,
        "title": s.title,
        "created_at": _utc(getattr(s, "created_at", None)).isoformat() if getattr(s, "created_at", None) else None,
        "updated_at": _utc(getattr(s, "updated_at", None)).isoformat() if getattr(s, "updated_at", None) else None,
        "messages": [
            {
                "role": m["role"],
                "content": m["content"],
                "tokens": m["tokens"],
                "created_at": (m["created_at"].isoformat() if m.get("created_at") else None),
            }
            for m in msgs
        ],
    }

    if fmt == "json":
        import json
        data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        return f"session_{s.id}.json", data, "application/json; charset=utf-8"

    # Markdown export
    lines = []
    title = s.title or s.id
    lines.append(f"# Session: {title}")
    if payload["created_at"]:
        lines.append(f"_Created_: {payload['created_at']}")
    if payload["updated_at"]:
        lines.append(f"_Updated_: {payload['updated_at']}")
    lines.append("")
    for m in msgs:
        ts = m.get("created_at")
        ts_s = ts.isoformat() if ts else ""
        lines.append(f"## {m['role'].capitalize()}  {('('+ts_s+')') if ts_s else ''}")
        lines.append("")
        lines.append(m["content"])
        lines.append("")
    md = "\n".join(lines).encode("utf-8")
    return f"session_{s.id}.md", md, "text/markdown; charset=utf-8"


# ------------------------- NEW: Memory helpers -------------------------------

def get_memory(session_id: str) -> Optional[str]:  # <-- ADDED: fetch pinned memory for a session
    """
    Return the pinned session memory (compact summary) or None if not set.
    """
    s = db.session.get(Session, session_id)
    if not s:
        raise ValueError("session_not_found")  # <-- ADDED: align error contract used elsewhere
    return s.memory  # type: ignore[attr-defined]  # <-- ADDED: column added in models/migration


def update_memory(session_id: str, memory_text: Optional[str]) -> Session:  # <-- ADDED: set/clear pinned memory
    """
    Update (or clear) the pinned session memory. Returns the updated Session.
    Callers should perform summarization/truncation before invoking this setter.
    """
    s = db.session.get(Session, session_id)
    if not s:
        raise ValueError("session_not_found")  # <-- ADDED

    s.memory = memory_text  # type: ignore[attr-defined]  # <-- ADDED
    s.updated_at = db.func.now()  # type: ignore[assignment]  # <-- ADDED: touch parent timestamp

    db.session.commit()  # <-- ADDED: persist changes
    db.session.refresh(s)  # <-- ADDED: reflect DB-side computed fields
    return s  # <-- ADDED
