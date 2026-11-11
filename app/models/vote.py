import uuid

from sqlalchemy import ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin


class FitVote(TimestampMixin, Base):
    """One viewer's answer to a fit's poll (Fit.poll_options).

    One row per (user, fit). Changing your mind updates `option` rather than
    adding a second vote — `updated_at` records when — and retracting deletes
    the row. A fit's author may vote on their own fit.
    """

    __tablename__ = "fit_votes"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    fit_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fits.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    # Index into the fit's poll_options. The poll can't change once anyone has voted, so
    # the index keeps pointing at the same answer.
    option: Mapped[int] = mapped_column(Integer)
