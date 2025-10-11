# server/models.py
from __future__ import annotations

# SQLAlchemy models for Sessions & Messages.
# - Uses string UUIDs (36 chars) for cross-DB portability.
# - Timestamps are timezone-aware where supported by the DB.
# - FK has ON DELETE CASCADE; for SQLite we enable PRAGMA foreign_keys.

import uuid
from datetime import datetime

from sqlalchemy import (
    Column,
    String,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    event,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

# --- CHANGED: mode-aware import so this file works in both launch modes ----
try:
    # Package mode: gunicorn server.app:app
    from .config import db  # noqa: F401
except Exception:  # noqa: BLE001
    # Top-level mode: gunicorn --chdir server app:app
    from config import db  # type: ignore
# --------------------------------------------------------------------------


# Define a small enum for message roles
MessageRole = Enum("user", "assistant", name="message_role")  # reuses naming_convention


def _uuid() -> str:
    """Generate a RFC4122 string UUID."""
    return str(uuid.uuid4())


class Session(db.Model):
    __tablename__ = "sessions"

    id = Column(String(36), primary_key=True, default=_uuid)  # string UUID PK
    title = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    # Relationship to messages; cascade delete handled by FK and ORM
    messages = relationship(
        "Message",
        back_populates="session",
        passive_deletes=True,  # rely on DB cascade
        order_by="Message.created_at.asc()",
    )

    def __repr__(self) -> str:
        return f"<Session id={self.id} title={self.title!r}>"


class Message(db.Model):
    __tablename__ = "messages"

    id = Column(String(36), primary_key=True, default=_uuid)  # string UUID PK
    session_id = Column(
        String(36),
        ForeignKey("sessions.id", ondelete="CASCADE"),  # ensure cascade on session delete
        nullable=False,
        index=True,
    )
    role = Column(MessageRole, nullable=False)  # 'user' | 'assistant'
    content = Column(String, nullable=False)
    tokens = Column(db.Integer, nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    session = relationship("Session", back_populates="messages")

    def __repr__(self) -> str:
        return f"<Message id={self.id} session_id={self.session_id} role={self.role}>"


# Composite index to optimize timeline fetches in a session.
Index("ix_messages_session_created_at", Message.session_id, Message.created_at)


# SQLite: ensure FK cascades are enforced.
# This is safe for Postgres and other engines; code executes only for sqlite.
@event.listens_for(db.engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):  # noqa: D401
    """Enable foreign key constraints for SQLite."""
    try:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
    except Exception:
        # Non-sqlite engines will ignore this without harm.
        pass
