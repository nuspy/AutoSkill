"""step checkpoints and replay: navigate the past steps of a procedure and re-run one

Every step row now carries the state as it was *before* the step ran (`checkpoint`), which is what
makes rewinding possible: the engine can put the procedure back exactly where it was and run the
step again. `procedures.replay` holds the replay in progress, with a stash of the state the user
would return to if they throw the re-run away, so a rewind is never a one-way door.

Nothing is deleted when a step is replaced: the old rows stay with status 'superseded' (a replay
was accepted over them) or 'discarded' (the replay itself was thrown away), so the history of what
the procedure actually did remains readable.

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-06 12:30:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0014'
down_revision = '0013'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('procedure_steps', schema=None) as batch_op:
        batch_op.add_column(sa.Column('checkpoint', sa.JSON(), nullable=True))

    with op.batch_alter_table('procedures', schema=None) as batch_op:
        batch_op.add_column(sa.Column('replay', sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('procedures', schema=None) as batch_op:
        batch_op.drop_column('replay')

    with op.batch_alter_table('procedure_steps', schema=None) as batch_op:
        batch_op.drop_column('checkpoint')
