"""ratings, contributions, curated lists, external git mirror

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-04 12:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0012'
down_revision = '0011'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('ratings',
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('skill_id', sa.String(length=36), nullable=False),
    sa.Column('skill_version_id', sa.String(length=36), nullable=True),
    sa.Column('stars', sa.Integer(), nullable=False),
    sa.Column('comment', sa.Text(), nullable=True),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['skill_id'], ['skills.id'], name=op.f('fk_ratings_skill_id_skills'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_ratings_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ratings')),
    sa.UniqueConstraint('user_id', 'skill_id', name='uq_rating')
    )
    with op.batch_alter_table('ratings', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_ratings_skill_id'), ['skill_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_ratings_user_id'), ['user_id'], unique=False)
    op.create_table('contributions',
    sa.Column('source_skill_id', sa.String(length=36), nullable=False),
    sa.Column('source_version_id', sa.String(length=36), nullable=False),
    sa.Column('target_skill_id', sa.String(length=36), nullable=False),
    sa.Column('target_version_id', sa.String(length=36), nullable=True),
    sa.Column('proposed_by', sa.String(length=36), nullable=False),
    sa.Column('message', sa.Text(), nullable=True),
    sa.Column('state', sa.String(length=16), nullable=False),
    sa.Column('decided_by', sa.String(length=36), nullable=True),
    sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('decision_comment', sa.Text(), nullable=True),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['source_skill_id'], ['skills.id'], name=op.f('fk_contributions_source_skill_id_skills'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['target_skill_id'], ['skills.id'], name=op.f('fk_contributions_target_skill_id_skills'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_contributions'))
    )
    with op.batch_alter_table('contributions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_contributions_source_skill_id'), ['source_skill_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_contributions_target_skill_id'), ['target_skill_id'], unique=False)
    op.create_table('curated_lists',
    sa.Column('slug', sa.String(length=80), nullable=False),
    sa.Column('name', sa.JSON(), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('ordinal', sa.Integer(), nullable=False),
    sa.Column('is_public', sa.Boolean(), nullable=False),
    sa.Column('created_by', sa.String(length=36), nullable=True),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_curated_lists'))
    )
    with op.batch_alter_table('curated_lists', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_curated_lists_slug'), ['slug'], unique=True)
    op.create_table('curated_list_items',
    sa.Column('list_id', sa.String(length=36), nullable=False),
    sa.Column('skill_id', sa.String(length=36), nullable=False),
    sa.Column('ordinal', sa.Integer(), nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.ForeignKeyConstraint(['list_id'], ['curated_lists.id'], name=op.f('fk_curated_list_items_list_id_curated_lists'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['skill_id'], ['skills.id'], name=op.f('fk_curated_list_items_skill_id_skills'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_curated_list_items')),
    sa.UniqueConstraint('list_id', 'skill_id', name='uq_list_item')
    )
    with op.batch_alter_table('curated_list_items', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_curated_list_items_list_id'), ['list_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_curated_list_items_skill_id'), ['skill_id'], unique=False)
    with op.batch_alter_table('skills', schema=None) as batch_op:
        batch_op.add_column(sa.Column('rating_avg', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('rating_count', sa.Integer(), nullable=False, server_default='0'))
    with op.batch_alter_table('skill_repos', schema=None) as batch_op:
        batch_op.add_column(sa.Column('external_remote_url', sa.String(length=500), nullable=True))
        batch_op.add_column(sa.Column('external_token_encrypted', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('last_external_push_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('last_external_error', sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('skill_repos', schema=None) as batch_op:
        batch_op.drop_column('last_external_error')
        batch_op.drop_column('last_external_push_at')
        batch_op.drop_column('external_token_encrypted')
        batch_op.drop_column('external_remote_url')
    with op.batch_alter_table('skills', schema=None) as batch_op:
        batch_op.drop_column('rating_count')
        batch_op.drop_column('rating_avg')
    with op.batch_alter_table('curated_list_items', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_curated_list_items_skill_id'))
        batch_op.drop_index(batch_op.f('ix_curated_list_items_list_id'))
    op.drop_table('curated_list_items')
    with op.batch_alter_table('curated_lists', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_curated_lists_slug'))
    op.drop_table('curated_lists')
    with op.batch_alter_table('contributions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_contributions_target_skill_id'))
        batch_op.drop_index(batch_op.f('ix_contributions_source_skill_id'))
    op.drop_table('contributions')
    with op.batch_alter_table('ratings', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_ratings_user_id'))
        batch_op.drop_index(batch_op.f('ix_ratings_skill_id'))
    op.drop_table('ratings')
