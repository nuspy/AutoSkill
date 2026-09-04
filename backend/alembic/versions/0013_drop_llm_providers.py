"""drop llm_providers: llmswitch is the only source of the provider choice

The table held a model, a base URL and an encrypted API key per project or for the whole system.
That configuration belongs to the machine the server runs on, not to a row the application can
edit, so it now lives in the llmswitch registry file outside the repository. The rows are dropped
with their keys: nothing reads them any more, and keeping dead credentials in a database is worse
than losing a setting that takes a minute to type again in Administration -> AI providers.

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-04 11:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0013'
down_revision = '0012'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('llm_providers', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_llm_providers_project_id'))

    op.drop_table('llm_providers')


def downgrade() -> None:
    # The shape comes back; the providers do not — see the note above.
    op.create_table('llm_providers',
    sa.Column('scope', sa.String(length=16), nullable=False),
    sa.Column('project_id', sa.String(length=36), nullable=True),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('adapter', sa.String(length=32), nullable=False),
    sa.Column('base_url', sa.String(length=500), nullable=True),
    sa.Column('model', sa.String(length=200), nullable=False),
    sa.Column('models', sa.JSON(), nullable=False),
    sa.Column('api_key_encrypted', sa.String(length=2000), nullable=True),
    sa.Column('extra', sa.JSON(), nullable=False),
    sa.Column('purposes', sa.JSON(), nullable=False),
    sa.Column('is_default', sa.Boolean(), nullable=False),
    sa.Column('is_enabled', sa.Boolean(), nullable=False),
    sa.Column('health', sa.JSON(), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_llm_providers_project_id_projects'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_llm_providers'))
    )
    with op.batch_alter_table('llm_providers', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_llm_providers_project_id'), ['project_id'], unique=False)
