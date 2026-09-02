"""Add provider-native collaboration events to chat messages.

Revision ID: c0d3c011ab01
Revises: 4ff2545411ad
Create Date: 2026-09-02
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "c0d3c011ab01"
down_revision = "4ff2545411ad"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "chat_message",
        sa.Column("collaboration_events", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("chat_message", "collaboration_events")
