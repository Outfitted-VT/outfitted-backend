"""add images and user profiles

Revision ID: e9100968dc55
Revises: 4b02d89674b0
Create Date: 2026-10-19 16:11:23.521059

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e9100968dc55'
down_revision: Union[str, Sequence[str], None] = '4b02d89674b0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('images',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('owner_id', sa.Uuid(), nullable=False),
    sa.Column('storage_key', sa.String(length=255), nullable=False),
    sa.Column('width', sa.Integer(), nullable=False),
    sa.Column('height', sa.Integer(), nullable=False),
    sa.Column('size_bytes', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_images_owner_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_images')),
    sa.UniqueConstraint('storage_key', name=op.f('uq_images_storage_key'))
    )
    op.create_index(op.f('ix_images_owner_id'), 'images', ['owner_id'], unique=False)

    # Existing users have no username, so add the column as nullable, give everyone a
    # placeholder they can change later, then make it required.
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('username', sa.String(length=30), nullable=True))

    if op.get_context().dialect.name == 'postgresql':
        op.execute(
            "UPDATE users SET username = 'user_' || left(replace(id::text, '-', ''), 12) "
            "WHERE username IS NULL"
        )
    else:
        users = sa.table('users', sa.column('id', sa.Uuid()), sa.column('username', sa.String()))
        connection = op.get_bind()
        for (user_id,) in connection.execute(sa.select(users.c.id)).all():
            connection.execute(
                users.update().where(users.c.id == user_id).values(username=f"user_{user_id.hex[:12]}")
            )

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.alter_column('username', existing_type=sa.String(length=30), nullable=False)
        batch_op.add_column(sa.Column('bio', sa.String(length=160), nullable=True))
        batch_op.add_column(sa.Column('avatar_image_id', sa.Uuid(), nullable=True))
        batch_op.create_index(batch_op.f('ix_users_username'), ['username'], unique=True)
        batch_op.create_foreign_key(batch_op.f('fk_users_avatar_image_id_images'), 'images', ['avatar_image_id'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f('fk_users_avatar_image_id_images'), type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_users_username'))
        batch_op.drop_column('avatar_image_id')
        batch_op.drop_column('bio')
        batch_op.drop_column('username')

    op.drop_index(op.f('ix_images_owner_id'), table_name='images')
    op.drop_table('images')
