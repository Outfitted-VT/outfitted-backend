"""Add Fit Stories (stories, story views)

Revision ID: 2f3ab022d16c
Revises: 744722d28f99
Create Date: 2026-11-09 21:41:18.983575

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2f3ab022d16c'
down_revision: Union[str, Sequence[str], None] = '744722d28f99'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('stories',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('image_id', sa.Uuid(), nullable=False),
    sa.Column('caption', sa.String(length=200), nullable=True),
    sa.Column('fit_id', sa.Uuid(), nullable=True),
    sa.Column('visibility', sa.String(length=20), server_default='public', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['fit_id'], ['fits.id'], name=op.f('fk_stories_fit_id_fits'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['image_id'], ['images.id'], name=op.f('fk_stories_image_id_images'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_stories_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_stories'))
    )
    with op.batch_alter_table('stories', schema=None) as batch_op:
        batch_op.create_index('ix_stories_user_id_expires_at', ['user_id', 'expires_at'], unique=False)

    op.create_table('story_views',
    sa.Column('story_id', sa.Uuid(), nullable=False),
    sa.Column('viewer_id', sa.Uuid(), nullable=False),
    sa.Column('viewed_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['story_id'], ['stories.id'], name=op.f('fk_story_views_story_id_stories'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['viewer_id'], ['users.id'], name=op.f('fk_story_views_viewer_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('story_id', 'viewer_id', name=op.f('pk_story_views'))
    )
    with op.batch_alter_table('story_views', schema=None) as batch_op:
        batch_op.create_index('ix_story_views_story_id_viewed_at', ['story_id', 'viewed_at'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('story_views', schema=None) as batch_op:
        batch_op.drop_index('ix_story_views_story_id_viewed_at')

    op.drop_table('story_views')
    with op.batch_alter_table('stories', schema=None) as batch_op:
        batch_op.drop_index('ix_stories_user_id_expires_at')

    op.drop_table('stories')
