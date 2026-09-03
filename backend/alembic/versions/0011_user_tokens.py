"""user tokens: invitations and password resets

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-04 10:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0011'
down_revision = '0010'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('user_tokens',
    sa.Column('kind', sa.String(length=24), nullable=False),
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('token_hash', sa.String(length=128), nullable=False),
    sa.Column('role', sa.String(length=16), nullable=True),
    sa.Column('project_id', sa.String(length=36), nullable=True),
    sa.Column('invited_by', sa.String(length=36), nullable=True),
    sa.Column('user_id', sa.String(length=36), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_user_tokens')),
    sa.UniqueConstraint('token_hash', name=op.f('uq_user_tokens_token_hash'))
    )
    with op.batch_alter_table('user_tokens', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_user_tokens_email'), ['email'], unique=False)
        batch_op.create_index(batch_op.f('ix_user_tokens_kind'), ['kind'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('user_tokens', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_user_tokens_kind'))
        batch_op.drop_index(batch_op.f('ix_user_tokens_email'))
    op.drop_table('user_tokens')
