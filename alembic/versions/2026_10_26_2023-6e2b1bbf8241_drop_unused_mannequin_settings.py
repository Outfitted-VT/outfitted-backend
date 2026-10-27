"""drop unused mannequin settings

Revision ID: 6e2b1bbf8241
Revises: caaa9d9fb45c
Create Date: 2026-10-26 20:23:41.330981

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6e2b1bbf8241'
down_revision: Union[str, Sequence[str], None] = 'caaa9d9fb45c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Nothing read these; they were only stored and returned by /users/me/privacy.
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('hide_facial_features')
        batch_op.drop_column('mannequin_tone')


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('mannequin_tone', sa.String(length=30), server_default='neutral_onyx', nullable=False))
        batch_op.add_column(sa.Column('hide_facial_features', sa.Boolean(), server_default=sa.false(), nullable=False))
