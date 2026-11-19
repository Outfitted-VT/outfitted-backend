"""Add Style a Friend

"Style me" requests and the looks sent back are chat messages (kinds style_request and
styled_look), so messages.kind gets longer. Pieces saved from a look remember it.

Revision ID: f4a1c8d2e6b3
Revises: e2b7d4f9a1c6
Create Date: 2026-11-18 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f4a1c8d2e6b3'
down_revision: Union[str, Sequence[str], None] = 'e2b7d4f9a1c6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('messages', schema=None) as batch_op:
        batch_op.alter_column('kind', existing_type=sa.String(length=12), type_=sa.String(length=20))
    with op.batch_alter_table('saved_pieces', schema=None) as batch_op:
        batch_op.add_column(sa.Column('look_message_id', sa.Uuid(), nullable=True))
        batch_op.add_column(sa.Column('look_index', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_saved_pieces_look_message_id'), ['look_message_id'], unique=False)
        batch_op.create_foreign_key(
            'fk_saved_pieces_look_message_id_messages', 'messages', ['look_message_id'], ['id'], ondelete='SET NULL'
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('saved_pieces', schema=None) as batch_op:
        batch_op.drop_constraint('fk_saved_pieces_look_message_id_messages', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_saved_pieces_look_message_id'))
        batch_op.drop_column('look_index')
        batch_op.drop_column('look_message_id')
    with op.batch_alter_table('messages', schema=None) as batch_op:
        batch_op.alter_column('kind', existing_type=sa.String(length=20), type_=sa.String(length=12))
