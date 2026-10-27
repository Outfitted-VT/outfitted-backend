"""drop unused users.avatar_mode

Revision ID: caaa9d9fb45c
Revises: c7f198b42e10
Create Date: 2026-10-26 20:20:42.696625

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'caaa9d9fb45c'
down_revision: Union[str, Sequence[str], None] = 'c7f198b42e10'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Nothing read avatar_mode; it was only stored and returned by /users/me/privacy.
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('avatar_mode')


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('avatar_mode', sa.String(length=20), server_default='photorealistic', nullable=False))
