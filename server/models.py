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

# Mode-aware import of db so this works in both launch modes (package/top-level).
try:
    # Package mode: gunicorn server.app:app
    from .config import db  # <-- keeps package mode working
except Exception:  # noqa: BLE001
    # Top-level mode: gunicorn --chdir server app:app
    from config import db  # type: ignore  # <-- fallback for top-level mode

# Define a small enum for message roles
MessageRole = Enum("user", "assistant", name="message_role")


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


# Register PRAGMA on generic Engine (NOT db.engine) so we don't require an
# application context at import time; only acts for SQLite connections.
from sqlalchemy.engine import Engine  # <-- added previously to avoid app ctx

@event.listens_for(Engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    """Enable foreign key constraints for SQLite (no-op for Postgres)."""
    try:
        from sqlite3 import Connection as SQLite3Connection
        if isinstance(dbapi_connection, SQLite3Connection):  # only SQLite
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
    except Exception:
        # Non-sqlite engines or environments without sqlite will safely no-op.
        pass
