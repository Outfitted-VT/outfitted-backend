import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import utcnow


class FitLike(Base):
    __tablename__ = "fit_likes"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    fit_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fits.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )


class FitSave(Base):
    """A fit bookmarked by a user. Private: only the saver sees their saves."""

    __tablename__ = "fit_saves"
    # "My saved fits" lists a user's saves newest first.
    __table_args__ = (Index("ix_fit_saves_user_id_created_at", "user_id", "created_at"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    fit_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fits.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
