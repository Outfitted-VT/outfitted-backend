"""Add saved pieces

Users can save a single piece (a shoe, a sweater) from a fit instead of the whole fit.

Revision ID: a7d4c2e9b1f3
Revises: 5c3e9a1f7b2d
Create Date: 2026-11-16 17:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7d4c2e9b1f3'
down_revision: Union[str, Sequence[str], None] = '5c3e9a1f7b2d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'saved_pieces',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('fit_id', sa.Uuid(), nullable=True),
        sa.Column('source_username', sa.String(length=30), nullable=True),
        sa.Column('category', sa.String(length=20), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('brand', sa.String(length=100), nullable=True),
        sa.Column('color', sa.String(length=50), nullable=True),
        sa.Column('url', sa.String(length=2048), nullable=True),
        sa.Column('image_id', sa.Uuid(), nullable=True),
        sa.Column('pin_x', sa.Float(), nullable=True),
        sa.Column('pin_y', sa.Float(), nullable=True),
        sa.Column('zoom', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['fit_id'], ['fits.id'], name=op.f('fk_saved_pieces_fit_id_fits'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['image_id'], ['images.id'], name=op.f('fk_saved_pieces_image_id_images'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_saved_pieces_user_id_users'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_saved_pieces')),
    )
    with op.batch_alter_table('saved_pieces', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_saved_pieces_fit_id'), ['fit_id'], unique=False)
        batch_op.create_index('ix_saved_pieces_user_id_created_at', ['user_id', 'created_at'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('saved_pieces', schema=None) as batch_op:
        batch_op.drop_index('ix_saved_pieces_user_id_created_at')
        batch_op.drop_index(batch_op.f('ix_saved_pieces_fit_id'))
    op.drop_table('saved_pieces')
