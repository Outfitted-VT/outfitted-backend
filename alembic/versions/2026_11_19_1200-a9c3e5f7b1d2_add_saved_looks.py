"""Add saved looks

"Save the look" on a styled look from chat (Style a Friend) saves the whole look, listed with
your saved fits, instead of copying each piece into saved pieces.

Revision ID: a9c3e5f7b1d2
Revises: f4a1c8d2e6b3
Create Date: 2026-11-19 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a9c3e5f7b1d2'
down_revision: Union[str, Sequence[str], None] = 'f4a1c8d2e6b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'saved_looks',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('message_id', sa.Uuid(), nullable=True),
        sa.Column('conversation_id', sa.Uuid(), nullable=True),
        sa.Column('stylist_id', sa.Uuid(), nullable=True),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('tryon_image_id', sa.Uuid(), nullable=True),
        sa.Column('pieces', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], name=op.f('fk_saved_looks_conversation_id_conversations'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['message_id'], ['messages.id'], name=op.f('fk_saved_looks_message_id_messages'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['stylist_id'], ['users.id'], name=op.f('fk_saved_looks_stylist_id_users'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['tryon_image_id'], ['images.id'], name=op.f('fk_saved_looks_tryon_image_id_images'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_saved_looks_user_id_users'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_saved_looks')),
        sa.UniqueConstraint('user_id', 'message_id', name='uq_saved_looks_user_id_message_id'),
    )
    op.create_index('ix_saved_looks_user_id_created_at', 'saved_looks', ['user_id', 'created_at'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_saved_looks_user_id_created_at', table_name='saved_looks')
    op.drop_table('saved_looks')
