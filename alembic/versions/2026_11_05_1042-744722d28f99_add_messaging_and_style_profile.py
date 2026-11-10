"""Add messaging (conversations, members, messages, fit-check votes) and user style profile

Revision ID: 744722d28f99
Revises: e7c0d38ca88a
Create Date: 2026-11-05 10:42:05.738392

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '744722d28f99'
down_revision: Union[str, Sequence[str], None] = 'e7c0d38ca88a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('conversations',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('type', sa.String(length=10), nullable=False),
    sa.Column('title', sa.String(length=80), nullable=True),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('direct_key', sa.String(length=80), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_conversations_created_by_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_conversations')),
    sa.UniqueConstraint('direct_key', name=op.f('uq_conversations_direct_key'))
    )
    op.create_table('conversation_members',
    sa.Column('conversation_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('role', sa.String(length=10), nullable=False),
    sa.Column('last_read_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_delivered_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('muted', sa.Boolean(), server_default=sa.false(), nullable=False),
    sa.Column('hidden_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('joined_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], name=op.f('fk_conversation_members_conversation_id_conversations'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_conversation_members_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('conversation_id', 'user_id', name=op.f('pk_conversation_members'))
    )
    with op.batch_alter_table('conversation_members', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_conversation_members_user_id'), ['user_id'], unique=False)

    op.create_table('messages',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('conversation_id', sa.Uuid(), nullable=False),
    sa.Column('sender_id', sa.Uuid(), nullable=True),
    sa.Column('kind', sa.String(length=12), nullable=False),
    sa.Column('body', sa.Text(), nullable=True),
    sa.Column('payload', sa.JSON(), nullable=True),
    sa.Column('client_id', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('edited_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], name=op.f('fk_messages_conversation_id_conversations'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['sender_id'], ['users.id'], name=op.f('fk_messages_sender_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_messages'))
    )
    with op.batch_alter_table('messages', schema=None) as batch_op:
        batch_op.create_index('ix_messages_conversation_id_created_at', ['conversation_id', 'created_at'], unique=False)
        batch_op.create_index('ix_messages_sender_id_client_id', ['sender_id', 'client_id'], unique=True)

    op.create_table('fit_check_votes',
    sa.Column('message_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('vote', sa.String(length=10), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['message_id'], ['messages.id'], name=op.f('fk_fit_check_votes_message_id_messages'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_fit_check_votes_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('message_id', 'user_id', name=op.f('pk_fit_check_votes'))
    )
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('style_tags', sa.JSON(), server_default='[]', nullable=False))
        batch_op.add_column(sa.Column('fit_preference', sa.String(length=10), nullable=True))
        batch_op.add_column(sa.Column('top_size', sa.String(length=4), nullable=True))
        batch_op.add_column(sa.Column('bottom_size', sa.String(length=4), nullable=True))
        batch_op.add_column(sa.Column('feedback_tone', sa.String(length=10), nullable=True))
        batch_op.add_column(sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True))



def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('last_seen_at')
        batch_op.drop_column('feedback_tone')
        batch_op.drop_column('bottom_size')
        batch_op.drop_column('top_size')
        batch_op.drop_column('fit_preference')
        batch_op.drop_column('style_tags')

    op.drop_table('fit_check_votes')
    with op.batch_alter_table('messages', schema=None) as batch_op:
        batch_op.drop_index('ix_messages_sender_id_client_id')
        batch_op.drop_index('ix_messages_conversation_id_created_at')

    op.drop_table('messages')
    with op.batch_alter_table('conversation_members', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_conversation_members_user_id'))

    op.drop_table('conversation_members')
    op.drop_table('conversations')
