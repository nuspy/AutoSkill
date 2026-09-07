"""an interview can have an executor: the agent on the person's machine

The application still leads every phase and the person still answers in the browser. What changes is
that the interview stops being blind: when it needs a fact about the machine — does this folder
exist, which sheets has this workbook, does that endpoint answer — it can ask the agent instead of
asking the person to recall it.

`agent_token_hash` is what an agent presents to join a session, stored hashed exactly like a trial
token. `origin` records which door the session came in through. Existing sessions become
'browser' with no executor, which is precisely what they are.

Revision ID: 0016
Revises: 0015
Create Date: 2026-09-06 20:05:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0016'
down_revision = '0015'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('interview_sessions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('origin', sa.String(length=16), nullable=False, server_default='browser'))
        batch_op.add_column(sa.Column('agent_token_hash', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('device_id', sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column('agent_target', sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column('agent_last_seen_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.create_index(
            batch_op.f('ix_interview_sessions_agent_token_hash'), ['agent_token_hash'], unique=True
        )


def downgrade() -> None:
    with op.batch_alter_table('interview_sessions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_interview_sessions_agent_token_hash'))
        batch_op.drop_column('agent_last_seen_at')
        batch_op.drop_column('agent_target')
        batch_op.drop_column('device_id')
        batch_op.drop_column('agent_token_hash')
        batch_op.drop_column('origin')
