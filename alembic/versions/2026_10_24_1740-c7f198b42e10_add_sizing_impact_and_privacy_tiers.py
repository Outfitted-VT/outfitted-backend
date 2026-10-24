"""add sizing impact and privacy tiers

Revision ID: c7f198b42e10
Revises: a04822f7251a
Create Date: 2026-10-24 17:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c7f198b42e10'
down_revision: Union[str, Sequence[str], None] = 'a04822f7251a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Create user_reference_garments table for TrueSize Passport
    op.create_table(
        'user_reference_garments',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('brand', sa.String(length=80), nullable=False),
        sa.Column('category', sa.String(length=30), nullable=False),
        sa.Column('item_name', sa.String(length=120), nullable=False),
        sa.Column('size', sa.String(length=30), nullable=False),
        sa.Column('fit_feeling', sa.String(length=30), server_default='perfect', nullable=False),
        sa.Column('is_favorite', sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_user_reference_garments_user_id_users'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_user_reference_garments'))
    )
    with op.batch_alter_table('user_reference_garments', schema=None) as batch_op:
        batch_op.create_index('ix_user_reference_garments_user_id', ['user_id'], unique=False)
        batch_op.create_index('ix_user_reference_garments_brand', ['brand'], unique=False)
        batch_op.create_index('ix_user_reference_garments_category', ['category'], unique=False)

    # 2. Create return_impact_records table
    op.create_table(
        'return_impact_records',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('fit_id', sa.Uuid(), nullable=True),
        sa.Column('item_name', sa.String(length=140), nullable=False),
        sa.Column('brand', sa.String(length=80), nullable=True),
        sa.Column('category', sa.String(length=40), nullable=True),
        sa.Column('estimated_price', sa.Float(), server_default='65.0', nullable=False),
        sa.Column('action_type', sa.String(length=50), nullable=False),
        sa.Column('dollars_saved', sa.Float(), server_default='32.0', nullable=False),
        sa.Column('co2_saved_kg', sa.Float(), server_default='1.8', nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['fit_id'], ['fits.id'], name=op.f('fk_return_impact_records_fit_id_fits'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_return_impact_records_user_id_users'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_return_impact_records'))
    )
    with op.batch_alter_table('return_impact_records', schema=None) as batch_op:
        batch_op.create_index('ix_return_impact_records_user_id', ['user_id'], unique=False)

    # 3. Add avatar privacy columns to users
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('avatar_mode', sa.String(length=20), server_default='photorealistic', nullable=False))
        batch_op.add_column(sa.Column('mannequin_tone', sa.String(length=30), server_default='neutral_onyx', nullable=False))
        batch_op.add_column(sa.Column('hide_facial_features', sa.Boolean(), server_default=sa.false(), nullable=False))
        batch_op.add_column(sa.Column('default_closet_privacy', sa.String(length=20), server_default='public', nullable=False))

    # 4. Add closet privacy and peer try-on columns to fits
    with op.batch_alter_table('fits', schema=None) as batch_op:
        batch_op.add_column(sa.Column('privacy_tier', sa.String(length=20), server_default='public', nullable=False))
        batch_op.add_column(sa.Column('allow_friend_try_on', sa.Boolean(), server_default=sa.true(), nullable=False))
        batch_op.create_index('ix_fits_privacy_tier', ['privacy_tier'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('fits', schema=None) as batch_op:
        batch_op.drop_index('ix_fits_privacy_tier')
        batch_op.drop_column('allow_friend_try_on')
        batch_op.drop_column('privacy_tier')

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('default_closet_privacy')
        batch_op.drop_column('hide_facial_features')
        batch_op.drop_column('mannequin_tone')
        batch_op.drop_column('avatar_mode')

    with op.batch_alter_table('return_impact_records', schema=None) as batch_op:
        batch_op.drop_index('ix_return_impact_records_user_id')

    op.drop_table('return_impact_records')

    with op.batch_alter_table('user_reference_garments', schema=None) as batch_op:
        batch_op.drop_index('ix_user_reference_garments_category')
        batch_op.drop_index('ix_user_reference_garments_brand')
        batch_op.drop_index('ix_user_reference_garments_user_id')

    op.drop_table('user_reference_garments')
