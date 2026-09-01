"""Add virtual LLM model routing.

Revision ID: 9d2e7a41c6bf
Revises: 34fe28843029
Create Date: 2026-08-31

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "9d2e7a41c6bf"
down_revision = "34fe28843029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "virtual_llm_model",
        sa.Column("model_configuration_id", sa.Integer(), nullable=False),
        sa.Column("target_model_configuration_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["model_configuration_id"],
            ["model_configuration.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["target_model_configuration_id"],
            ["model_configuration.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("model_configuration_id"),
    )
    op.create_index(
        "ix_virtual_llm_model_target_model_configuration_id",
        "virtual_llm_model",
        ["target_model_configuration_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_virtual_llm_model_target_model_configuration_id",
        table_name="virtual_llm_model",
    )
    op.drop_table("virtual_llm_model")
