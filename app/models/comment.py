import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import utcnow


class FitComment(Base):
    __tablename__ = "fit_comments"
    __table_args__ = (Index("ix_fit_comments_fit_id_created_at", "fit_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    fit_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fits.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )

    author = relationship("User", lazy="joined")
    fit = relationship("Fit", lazy="select")
