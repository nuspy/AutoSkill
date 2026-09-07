"""Keep the trial token recoverable so the install command can be shown again.

The token was stored only as a hash. That is the correct shape for a bearer secret and the wrong one
for this particular secret: the install command is the only thing that starts a trial, it was shown
once in the dialog that created it, and once that dialog closed there was no way back to it. The
trial page could offer nothing but "issue a new token" — which invalidates the one the person may
already have pasted into an agent, so recovering the instruction broke the installation it was meant
to explain.

`DownloadGrant` had already solved exactly this, in this codebase, by keeping both: the hash for
lookup and an encrypted copy so the UI can display the value again. This does the same.

Nullable on purpose: trials created before this migration have no stored copy, and for those the
re-issue path remains the only way.

Revision ID: 0017
Revises: 0016
"""

import sqlalchemy as sa

from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("trial_sessions", sa.Column("token_encrypted", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("trial_sessions", "token_encrypted")
