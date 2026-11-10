import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import utcnow


class UserStreak(Base):
    """Consecutive local days with a fit, story, or fit check. Dates are in the user's timezone.
    frozen_date is the missed day a freeze covered, when it came after last_active_date."""

    __tablename__ = "user_streaks"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    current_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    longest_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_active_date: Mapped[date | None] = mapped_column(Date)
    frozen_date: Mapped[date | None] = mapped_column(Date)
    freezes_available: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_reminded_date: Mapped[date | None] = mapped_column(Date)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), onupdate=utcnow
    )
