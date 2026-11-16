"""Add image to fit items

A piece can carry a photo of just itself (for a try-on post, the clothing photo it was tried on
from), shown in the shop / save bubble and kept on saved pieces.

Revision ID: c3f8e1a2d5b7
Revises: a7d4c2e9b1f3
Create Date: 2026-11-16 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3f8e1a2d5b7'
down_revision: Union[str, Sequence[str], None] = 'a7d4c2e9b1f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('fit_items', schema=None) as batch_op:
        batch_op.add_column(sa.Column('image_id', sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(
            batch_op.f('fk_fit_items_image_id_images'), 'images', ['image_id'], ['id'], ondelete='SET NULL'
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('fit_items', schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f('fk_fit_items_image_id_images'), type_='foreignkey')
        batch_op.drop_column('image_id')
