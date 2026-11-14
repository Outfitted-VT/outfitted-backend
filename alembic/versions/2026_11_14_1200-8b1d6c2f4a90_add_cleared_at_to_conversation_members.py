"""Add cleared_at to conversation members

When a member deletes a direct chat, they stop seeing its earlier messages; the other
person keeps them.

Revision ID: 8b1d6c2f4a90
Revises: 63227d352e5e
Create Date: 2026-11-14 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8b1d6c2f4a90'
down_revision: Union[str, Sequence[str], None] = '63227d352e5e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('conversation_members', schema=None) as batch_op:
        batch_op.add_column(sa.Column('cleared_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('conversation_members', schema=None) as batch_op:
        batch_op.drop_column('cleared_at')
