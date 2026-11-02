"""add wardrobe items and outfit memories

Revision ID: e1f2a3b4c5d6
Revises: 4c482e3ac389, d8e9f1a2b3c4
Create Date: 2026-11-02 16:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e1f2a3b4c5d6'
down_revision: Union[str, Sequence[str], None] = ('4c482e3ac389', 'd8e9f1a2b3c4')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create wardrobe_items table
    op.create_table(
        'wardrobe_items',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('primary_category', sa.String(length=30), nullable=False),
        sa.Column('sub_category', sa.String(length=50), nullable=True),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('brand', sa.String(length=100), nullable=True),
        sa.Column('color', sa.String(length=50), nullable=True),
        sa.Column('price', sa.Float(), server_default='0.0', nullable=False),
        sa.Column('times_worn', sa.Integer(), server_default='0', nullable=False),
        sa.Column('last_worn_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('tag', sa.String(length=80), nullable=True),
        sa.Column('image_url', sa.String(length=2048), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_wardrobe_items_user_id', 'wardrobe_items', ['user_id'], unique=False)
    op.create_index('ix_wardrobe_items_primary_category', 'wardrobe_items', ['primary_category'], unique=False)
    op.create_index('ix_wardrobe_items_user_category', 'wardrobe_items', ['user_id', 'primary_category'], unique=False)

    # 2. Create outfit_memories table
    op.create_table(
        'outfit_memories',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('date', sa.String(length=10), nullable=False),
        sa.Column('title', sa.String(length=150), nullable=False),
        sa.Column('photo_url', sa.String(length=2048), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('weather', sa.String(length=100), nullable=True),
        sa.Column('rating', sa.Integer(), server_default='5', nullable=False),
        sa.Column('tagged_pieces', sa.Text(), server_default='[]', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_outfit_memories_user_id', 'outfit_memories', ['user_id'], unique=False)
    op.create_index('ix_outfit_memories_date', 'outfit_memories', ['date'], unique=False)
    op.create_index('ix_outfit_memories_user_date', 'outfit_memories', ['user_id', 'date'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_outfit_memories_user_date', table_name='outfit_memories')
    op.drop_index('ix_outfit_memories_date', table_name='outfit_memories')
    op.drop_index('ix_outfit_memories_user_id', table_name='outfit_memories')
    op.drop_table('outfit_memories')

    op.drop_index('ix_wardrobe_items_user_category', table_name='wardrobe_items')
    op.drop_index('ix_wardrobe_items_primary_category', table_name='wardrobe_items')
    op.drop_index('ix_wardrobe_items_user_id', table_name='wardrobe_items')
    op.drop_table('wardrobe_items')
