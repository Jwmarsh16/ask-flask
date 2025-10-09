# server/services/session_store.py
"""
Service/repository layer for Session & Message operations.

This isolates DB logic from Flask routes. Routes can call these
functions directly (JSON DTO mapping done at the edge).
"""

from __future__ import annotations

from typing import Iterable, List, Optional, Tuple, Literal, Dict, Any

from sqlalchemy import func, select, desc, case, literal_column
from sqlalchemy.orm import Session as OrmSession

from .config import db
from .models import Session as ChatSession, Message


def create_session(title: Optional[str] = None) -> ChatSession:
    s = ChatSession(title=title)
    db.session.add(s)
    db.session.commit()
    return s


def list_sessions() -> List[Dict[str, Any]]:
    """
    Return sessions with computed last_activity (max(message.created_at) or updated_at).
    """
    # LEFT OUTER JOIN messages to compute last_activity.
    subq = (
        db.session.query(
            Message.session_id.label("sid"),
            func.max(Message.created_at).label("last_msg_at"),
        )
        .group_by(Message.session_id)
        .subquery()
    )

    rows = (
        db.session.query(
            ChatSession.id,
            ChatSession.title,
            ChatSession.created_at,
            func.coalesce(subq.c.last_msg_at, ChatSession.updated_at).label("last_activity"),
        )
        .outerjoin(subq, subq.c.sid == ChatSession.id)
        .order_by(desc("last_activity"))
        .all()
    )

    return [
        {
            "id": r.id,
            "title": r.title,
            "created_at": r.created_at,
            "last_activity": r.last_activity,
        }
        for r in rows
    ]


def get_session_messages(session_id: str) -> List[Dict[str, Any]]:
    msgs = (
        db.session.query(Message)
        .filter(Message.session_id == session_id)
        .order_by(Message.created_at.asc())
        .all()
    )
    return [
        {
            "id": m.id,
            "role": str(m.role),
            "content": m.content,
            "tokens": m.tokens,
            "created_at": m.created_at,
        }
        for m in msgs
    ]


def append_message(session_id: str, role: Literal["user", "assistant"], content: str, tokens: Optional[int] = None) -> Message:
    # Optional: assert the session exists; raise if not found. // ADDED
    s = db.session.get(ChatSession, session_id)
    if not s:
        raise ValueError("Session not found")

    msg = Message(session_id=session_id, role=role, content=content, tokens=tokens)
    db.session.add(msg)

    # Touch parent updated_at via ORM flush (onupdate=func.now()). // ADDED
    # Explicitly mark the parent dirty so onupdate fires on commit.
    db.session.add(s)

    db.session.commit()
    return msg


def delete_session(session_id: str) -> bool:
    s = db.session.get(ChatSession, session_id)
    if not s:
        return False
    db.session.delete(s)
    db.session.commit()
    return True


def export_session(session_id: str, fmt: Literal["json", "md"]) -> Tuple[str, bytes, str]:
    """
    Export a session in JSON or Markdown.

    Returns (filename, data_bytes, mime_type).
    """
    s = db.session.get(ChatSession, session_id)
    if not s:
        raise ValueError("Session not found")
    messages = (
        db.session.query(Message).filter_by(session_id=session_id).order_by(Message.created_at.asc()).all()
    )

    if fmt == "json":
        payload = {
            "session": {
                "id": s.id,
                "title": s.title,
                "created_at": s.created_at.isoformat() if s.created_at else None,
                "updated_at": s.updated_at.isoformat() if s.updated_at else None,
            },
            "messages": [
                {
                    "id": m.id,
                    "role": str(m.role),
                    "content": m.content,
                    "tokens": m.tokens,
                    "created_at": m.created_at.isoformat() if m.created_at else None,
                }
                for m in messages
            ],
        }
        name = f"session_{s.id}.json"
        return name, (repr(payload) if False else  # keep repr path for debugging if needed
                      # Serialize compactly to bytes:
                      (str(payload).encode("utf-8") if False else __import__("json").dumps(payload, separators=(",", ":")).encode("utf-8"))), "application/json"

    # Markdown rendering // ADDED
    lines = [f"# Session {s.id}", ""]
    if s.title:
      lines.insert(1, f"**Title:** {s.title}\n")
    for m in messages:
        ts = m.created_at.isoformat() if m.created_at else ""
        role = str(m.role)
        lines.append(f"## {role} — {ts}")
        lines.append("")
        lines.append(m.content)
        lines.append("")
    md = "\n".join(lines).encode("utf-8")
    name = f"session_{s.id}.md"
    return name, md, "text/markdown"
