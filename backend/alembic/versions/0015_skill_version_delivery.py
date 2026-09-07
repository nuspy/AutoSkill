"""how a version delivers its deterministic steps: scripts (default) or an MCP server

Scripts are the default because for most skills the MCP machinery is paid for nothing: the steps run
in a fixed order, so there is no choice for the agent to make, and every registered tool costs a
process and a slice of the model's context. An MCP server earns its keep when the agent has no shell
to run a command with, when a step needs authorisation per action, or when the tools are meant to be
reused by other skills.

Existing versions become 'script': it is the cheaper shape, and nothing installed changes until a
version is rebuilt.

Revision ID: 0015
Revises: 0014
Create Date: 2026-09-06 17:10:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0015'
down_revision = '0014'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('skill_versions', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('delivery', sa.String(length=16), nullable=False, server_default='script')
        )


def downgrade() -> None:
    with op.batch_alter_table('skill_versions', schema=None) as batch_op:
        batch_op.drop_column('delivery')
