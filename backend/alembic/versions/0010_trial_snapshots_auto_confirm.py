"""trial snapshots + auto_confirm

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-04 09:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0010'
down_revision = '0009'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('trial_snapshots',
    sa.Column('run_id', sa.String(length=36), nullable=False),
    sa.Column('trial_session_id', sa.String(length=36), nullable=True),
    sa.Column('step_key', sa.String(length=64), nullable=False),
    sa.Column('iteration', sa.Integer(), nullable=False),
    sa.Column('items', sa.JSON(), nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('taken_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('restored_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('restore_result', sa.JSON(), nullable=True),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.ForeignKeyConstraint(['run_id'], ['runs.id'], name=op.f('fk_trial_snapshots_run_id_runs'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_trial_snapshots'))
    )
    with op.batch_alter_table('trial_snapshots', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_trial_snapshots_run_id'), ['run_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_trial_snapshots_trial_session_id'), ['trial_session_id'], unique=False)
    with op.batch_alter_table('trial_sessions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('auto_confirm', sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade() -> None:
    with op.batch_alter_table('trial_sessions', schema=None) as batch_op:
        batch_op.drop_column('auto_confirm')
    with op.batch_alter_table('trial_snapshots', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_trial_snapshots_trial_session_id'))
        batch_op.drop_index(batch_op.f('ix_trial_snapshots_run_id'))
    op.drop_table('trial_snapshots')
