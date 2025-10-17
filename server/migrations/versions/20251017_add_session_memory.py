# server/migrations/versions/20251017_add_session_memory.py
"""add session memory column

Revision ID: b7c9d2e3f4a1
Revises: a1b2c3d4e5f6
Create Date: 2025-10-17 15:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "b7c9d2e3f4a1"          # NEW: unique revision id for this migration  # inline-change
down_revision = "a1b2c3d4e5f6"      # NEW: points to current head (sessions/messages)  # inline-change
branch_labels = None
depends_on = None


def upgrade():
    # Add nullable TEXT column 'memory' to 'sessions' for pinned session summary.
    # Works on SQLite and Postgres; no server_default so upgrades are lightweight.
    op.add_column("sessions", sa.Column("memory", sa.Text(), nullable=True))  # inline-change


def downgrade():
    # Drop the 'memory' column on downgrade.
    op.drop_column("sessions", "memory")  # inline-change
