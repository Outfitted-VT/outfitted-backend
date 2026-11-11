"""Add custom polls to fits

Each fit gets a poll question and 2–4 answers (both null for no poll), and a vote
records the index of the answer instead of "wear" / "rethink". Existing fits get
"Would you wear it?" with "Wear it" / "Rethink", so their votes keep their meaning
(wear -> 0, rethink -> 1).

Revision ID: 63227d352e5e
Revises: 645da2040462
Create Date: 2026-11-11 19:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '63227d352e5e'
down_revision: Union[str, Sequence[str], None] = '645da2040462'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

fits = sa.table('fits', sa.column('poll_question', sa.String), sa.column('poll_options', sa.JSON))
votes = sa.table(
    'fit_votes',
    sa.column('fit_id', sa.Uuid),
    sa.column('choice', sa.String),
    sa.column('option', sa.Integer),
)


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('fits', schema=None) as batch_op:
        batch_op.add_column(sa.Column('poll_question', sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column('poll_options', sa.JSON(), nullable=True))
    op.execute(fits.update().values(poll_question='Would you wear it?', poll_options=['Wear it', 'Rethink']))

    with op.batch_alter_table('fit_votes', schema=None) as batch_op:
        batch_op.add_column(sa.Column('option', sa.Integer(), nullable=True))
    op.execute(votes.update().values(option=sa.case((votes.c.choice == 'rethink', 1), else_=0)))
    with op.batch_alter_table('fit_votes', schema=None) as batch_op:
        batch_op.alter_column('option', existing_type=sa.Integer(), nullable=False)
        batch_op.drop_column('choice')


def downgrade() -> None:
    """Downgrade schema.

    Only the first two answers map back to wear / rethink, so votes for a third or
    fourth answer are deleted.
    """
    with op.batch_alter_table('fit_votes', schema=None) as batch_op:
        batch_op.add_column(sa.Column('choice', sa.String(length=10), nullable=True))
    op.execute(votes.delete().where(votes.c.option > 1))
    op.execute(votes.update().values(choice=sa.case((votes.c.option == 1, 'rethink'), else_='wear')))
    with op.batch_alter_table('fit_votes', schema=None) as batch_op:
        batch_op.alter_column('choice', existing_type=sa.String(length=10), nullable=False)
        batch_op.drop_column('option')

    with op.batch_alter_table('fits', schema=None) as batch_op:
        batch_op.drop_column('poll_options')
        batch_op.drop_column('poll_question')
