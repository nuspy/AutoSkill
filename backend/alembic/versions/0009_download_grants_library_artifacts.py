"""download grants + library component artifacts

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-03 18:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('download_grants',
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('token_hash', sa.String(length=128), nullable=False),
    sa.Column('token_encrypted', sa.Text(), nullable=False),
    sa.Column('skill_id', sa.String(length=36), nullable=False),
    sa.Column('skill_version_id', sa.String(length=36), nullable=False),
    sa.Column('trial_session_id', sa.String(length=36), nullable=True),
    sa.Column('target_agent', sa.String(length=32), nullable=True),
    sa.Column('created_by', sa.String(length=36), nullable=True),
    sa.Column('label', sa.String(length=120), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('download_count', sa.Integer(), nullable=False),
    sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['skill_id'], ['skills.id'], name=op.f('fk_download_grants_skill_id_skills'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['skill_version_id'], ['skill_versions.id'], name=op.f('fk_download_grants_skill_version_id_skill_versions'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_download_grants'))
    )
    with op.batch_alter_table('download_grants', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_download_grants_token_hash'), ['token_hash'], unique=True)
        batch_op.create_index(batch_op.f('ix_download_grants_skill_id'), ['skill_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_download_grants_skill_version_id'), ['skill_version_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_download_grants_trial_session_id'), ['trial_session_id'], unique=False)

    with op.batch_alter_table('library_components', schema=None) as batch_op:
        batch_op.add_column(sa.Column('artifact', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('install_paths', sa.JSON(), nullable=False, server_default='{}'))


def downgrade() -> None:
    with op.batch_alter_table('library_components', schema=None) as batch_op:
        batch_op.drop_column('install_paths')
        batch_op.drop_column('artifact')

    with op.batch_alter_table('download_grants', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_download_grants_trial_session_id'))
        batch_op.drop_index(batch_op.f('ix_download_grants_skill_version_id'))
        batch_op.drop_index(batch_op.f('ix_download_grants_skill_id'))
        batch_op.drop_index(batch_op.f('ix_download_grants_token_hash'))

    op.drop_table('download_grants')
