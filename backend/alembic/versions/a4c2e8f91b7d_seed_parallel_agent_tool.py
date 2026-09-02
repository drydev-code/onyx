"""seed parallel agent tool

Revision ID: a4c2e8f91b7d
Revises: 947b94d2ebf1
Create Date: 2026-09-02

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "a4c2e8f91b7d"
down_revision = "947b94d2ebf1"
branch_labels = None
depends_on = None


PARALLEL_AGENT_TOOL = {
    "name": "parallel_agents",
    "display_name": "Parallel Agents",
    "description": (
        "Split a complex objective into isolated tasks, run read-only worker "
        "agents in parallel, and synthesize their reports."
    ),
    "in_code_tool_id": "ParallelAgentTool",
    "enabled": True,
}


def upgrade() -> None:
    connection = op.get_bind()
    existing = connection.execute(
        sa.text("SELECT id FROM tool WHERE in_code_tool_id = :in_code_tool_id"),
        {"in_code_tool_id": PARALLEL_AGENT_TOOL["in_code_tool_id"]},
    ).fetchone()

    if existing:
        connection.execute(
            sa.text(
                """
                UPDATE tool
                SET name = :name,
                    display_name = :display_name,
                    description = :description,
                    enabled = :enabled
                WHERE in_code_tool_id = :in_code_tool_id
                """
            ),
            PARALLEL_AGENT_TOOL,
        )
    else:
        connection.execute(
            sa.text(
                """
                INSERT INTO tool
                    (name, display_name, description, in_code_tool_id, enabled)
                VALUES
                    (:name, :display_name, :description, :in_code_tool_id, :enabled)
                """
            ),
            PARALLEL_AGENT_TOOL,
        )


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text("DELETE FROM tool WHERE in_code_tool_id = :in_code_tool_id"),
        {"in_code_tool_id": PARALLEL_AGENT_TOOL["in_code_tool_id"]},
    )
