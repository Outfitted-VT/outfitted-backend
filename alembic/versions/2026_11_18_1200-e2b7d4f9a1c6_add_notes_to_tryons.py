"""Add notes to try-ons

A short description of each piece, or of the whole outfit ("relaxed oversized tee"), sent to the
model with its photo so the clothes keep their fit, and kept so "Try this look" reuses it.

Revision ID: e2b7d4f9a1c6
Revises: c3f8e1a2d5b7
Create Date: 2026-11-18 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e2b7d4f9a1c6'
down_revision: Union[str, Sequence[str], None] = 'c3f8e1a2d5b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('tryons', schema=None) as batch_op:
        batch_op.add_column(sa.Column('outfit_note', sa.String(length=100), nullable=True))
    with op.batch_alter_table('tryon_pieces', schema=None) as batch_op:
        batch_op.add_column(sa.Column('note', sa.String(length=100), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('tryon_pieces', schema=None) as batch_op:
        batch_op.drop_column('note')
    with op.batch_alter_table('tryons', schema=None) as batch_op:
        batch_op.drop_column('outfit_note')
