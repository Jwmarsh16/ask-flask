# server/migrations/versions/20251009_sessions_messages.py
"""add sessions and messages tables

Revision ID: a1b2c3d4e5f6
Revises: 6c081dbe19af
Create Date: 2025-10-09 19:30:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "a1b2c3d4e5f6"               # <-- ADDED: new revision id
down_revision = "6c081dbe19af"          # <-- CHANGED: set to your last migration id
branch_labels = None
depends_on = None


def upgrade():
    # Create 'sessions' table
    op.create_table(
        "sessions",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # Create 'messages' table
    op.create_table(
        "messages",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False, index=True),
        sa.Column("role", sa.Enum("user", "assistant", name="message_role"), nullable=False),
        sa.Column("content", sa.String(), nullable=False),
        sa.Column("tokens", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
    )

    # Composite index for fast timeline scans
    op.create_index(
        "ix_messages_session_created_at",
        "messages",
        ["session_id", "created_at"],
        unique=False,
    )


def downgrade():
    op.drop_index("ix_messages_session_created_at", table_name="messages")
    op.drop_table("messages")
    # Drop enum explicitly for some backends (safe if no-op on SQLite)
    try:
        sa.Enum(name="message_role").drop(op.get_bind(), checkfirst=True)
    except Exception:
        pass
    op.drop_table("sessions")
