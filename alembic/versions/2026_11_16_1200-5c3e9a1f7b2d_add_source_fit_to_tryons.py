"""Add source_fit_id to try-ons

"Try this look" try-ons remember the fit they came from, so a fit can show how many people
tried it.

Revision ID: 5c3e9a1f7b2d
Revises: 8b1d6c2f4a90
Create Date: 2026-11-16 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5c3e9a1f7b2d'
down_revision: Union[str, Sequence[str], None] = '8b1d6c2f4a90'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('tryons', schema=None) as batch_op:
        batch_op.add_column(sa.Column('source_fit_id', sa.Uuid(), nullable=True))
        batch_op.create_index(batch_op.f('ix_tryons_source_fit_id'), ['source_fit_id'], unique=False)
        batch_op.create_foreign_key(
            batch_op.f('fk_tryons_source_fit_id_fits'), 'fits', ['source_fit_id'], ['id'], ondelete='SET NULL'
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('tryons', schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f('fk_tryons_source_fit_id_fits'), type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_tryons_source_fit_id'))
        batch_op.drop_column('source_fit_id')
