import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin

# A viewer's verdict on a fit. Stored as a short string, like the other
# enum-ish columns in this app (Fit.privacy_tier, FitItem.category).
VOTE_CHOICES = ("wear", "rethink")


class FitVote(TimestampMixin, Base):
    """One viewer's verdict on a fit: "wear it" or "rethink".

    One row per (user, fit). Changing your mind updates `choice` rather than
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
    choice: Mapped[str] = mapped_column(String(10))
