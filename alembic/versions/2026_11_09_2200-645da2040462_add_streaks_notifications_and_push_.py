"""Add streaks, notifications, notification settings, push device tokens, and user timezone

Revision ID: 645da2040462
Revises: 2f3ab022d16c
Create Date: 2026-11-09 22:00:00.718606

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '645da2040462'
down_revision: Union[str, Sequence[str], None] = '2f3ab022d16c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('device_tokens',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('platform', sa.String(length=10), nullable=False),
    sa.Column('token', sa.String(length=512), nullable=False),
    sa.Column('app_version', sa.String(length=32), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_device_tokens_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_device_tokens')),
    sa.UniqueConstraint('token', name=op.f('uq_device_tokens_token'))
    )
    with op.batch_alter_table('device_tokens', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_device_tokens_user_id'), ['user_id'], unique=False)

    op.create_table('notification_settings',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('social', sa.Boolean(), server_default=sa.true(), nullable=False),
    sa.Column('messages', sa.Boolean(), server_default=sa.true(), nullable=False),
    sa.Column('stories', sa.Boolean(), server_default=sa.true(), nullable=False),
    sa.Column('streaks', sa.Boolean(), server_default=sa.true(), nullable=False),
    sa.Column('quiet_hours_start', sa.Time(), nullable=True),
    sa.Column('quiet_hours_end', sa.Time(), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_notification_settings_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', name=op.f('pk_notification_settings'))
    )
    op.create_table('notifications',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('actor_id', sa.Uuid(), nullable=True),
    sa.Column('type', sa.String(length=30), nullable=False),
    sa.Column('entity_type', sa.String(length=20), nullable=True),
    sa.Column('entity_id', sa.Uuid(), nullable=True),
    sa.Column('data', sa.JSON(), nullable=False),
    sa.Column('group_key', sa.String(length=100), nullable=True),
    sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['actor_id'], ['users.id'], name=op.f('fk_notifications_actor_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_notifications_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_notifications'))
    )
    with op.batch_alter_table('notifications', schema=None) as batch_op:
        batch_op.create_index('ix_notifications_user_id_created_at', ['user_id', 'created_at'], unique=False)
        batch_op.create_index('ix_notifications_user_id_group_key', ['user_id', 'group_key'], unique=False)
        batch_op.create_index('ix_notifications_user_id_read_at', ['user_id', 'read_at'], unique=False)

    op.create_table('user_streaks',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('current_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('longest_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('last_active_date', sa.Date(), nullable=True),
    sa.Column('frozen_date', sa.Date(), nullable=True),
    sa.Column('freezes_available', sa.Integer(), server_default='0', nullable=False),
    sa.Column('last_reminded_date', sa.Date(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_user_streaks_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', name=op.f('pk_user_streaks'))
    )
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('timezone', sa.String(length=64), server_default='UTC', nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('timezone')

    op.drop_table('user_streaks')
    with op.batch_alter_table('notifications', schema=None) as batch_op:
        batch_op.drop_index('ix_notifications_user_id_read_at')
        batch_op.drop_index('ix_notifications_user_id_group_key')
        batch_op.drop_index('ix_notifications_user_id_created_at')

    op.drop_table('notifications')
    op.drop_table('notification_settings')
    with op.batch_alter_table('device_tokens', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_device_tokens_user_id'))

    op.drop_table('device_tokens')
