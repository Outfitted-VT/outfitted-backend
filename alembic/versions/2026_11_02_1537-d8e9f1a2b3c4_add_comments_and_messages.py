"""add comments and messages

Revision ID: d8e9f1a2b3c4
Revises: c7f198b42e10
Create Date: 2026-11-02 15:37:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd8e9f1a2b3c4'
down_revision: Union[str, Sequence[str], None] = 'c7f198b42e10'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create fit_comments table
    op.create_table(
        'fit_comments',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('fit_id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['fit_id'], ['fits.id'], name=op.f('fk_fit_comments_fit_id_fits'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_fit_comments_user_id_users'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_fit_comments'))
    )
    with op.batch_alter_table('fit_comments', schema=None) as batch_op:
        batch_op.create_index('ix_fit_comments_fit_id_created_at', ['fit_id', 'created_at'], unique=False)
        batch_op.create_index('ix_fit_comments_fit_id', ['fit_id'], unique=False)
        batch_op.create_index('ix_fit_comments_user_id', ['user_id'], unique=False)

    # 2. Create direct_messages table
    op.create_table(
        'direct_messages',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('sender_id', sa.Uuid(), nullable=False),
        sa.Column('recipient_id', sa.Uuid(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('fit_id', sa.Uuid(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['fit_id'], ['fits.id'], name=op.f('fk_direct_messages_fit_id_fits'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['recipient_id'], ['users.id'], name=op.f('fk_direct_messages_recipient_id_users'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['sender_id'], ['users.id'], name=op.f('fk_direct_messages_sender_id_users'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_direct_messages'))
    )
    with op.batch_alter_table('direct_messages', schema=None) as batch_op:
        batch_op.create_index('ix_direct_messages_participants', ['sender_id', 'recipient_id', 'created_at'], unique=False)
        batch_op.create_index('ix_direct_messages_sender_id', ['sender_id'], unique=False)
        batch_op.create_index('ix_direct_messages_recipient_id', ['recipient_id'], unique=False)
        batch_op.create_index('ix_direct_messages_fit_id', ['fit_id'], unique=False)


def downgrade() -> None:
    op.drop_table('direct_messages')
    op.drop_table('fit_comments')
