import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import utcnow


class DirectMessage(Base):
    __tablename__ = "direct_messages"
    __table_args__ = (
        Index("ix_direct_messages_participants", "sender_id", "recipient_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    sender_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    recipient_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    content: Mapped[str] = mapped_column(Text)
    fit_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("fits.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )

    sender = relationship("User", foreign_keys=[sender_id], lazy="joined")
    recipient = relationship("User", foreign_keys=[recipient_id], lazy="joined")
    fit = relationship("Fit", foreign_keys=[fit_id], lazy="joined")
