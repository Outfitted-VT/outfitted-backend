import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import utcnow


class Follow(Base):
    """follower_id follows followee_id."""

    __tablename__ = "follows"
    __table_args__ = (
        CheckConstraint("follower_id != followee_id", name="no_self_follow"),
        # Follower lists (who follows X) and following lists (who X follows), newest first.
        Index("ix_follows_followee_id_created_at", "followee_id", "created_at"),
        Index("ix_follows_follower_id_created_at", "follower_id", "created_at"),
    )

    follower_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    followee_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
