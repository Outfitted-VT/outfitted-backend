import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

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


class SavedPiece(Base):
    """One piece (a shoe, a sweater) a user saved from a fit. Private to the saver.

    A copy, not a link: editing a fit rebuilds its items with new ids, and the poster may edit
    or delete it later, so the saved piece keeps its own name, link and photo. `fit_id` remembers
    where it came from while that fit exists. The photo is the fit's photo the piece was on, with
    the pin to centre on (`zoom` when several pieces share that photo)."""

    __tablename__ = "saved_pieces"
    # "My saved pieces" lists a user's saves newest first.
    __table_args__ = (Index("ix_saved_pieces_user_id_created_at", "user_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    fit_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("fits.id", ondelete="SET NULL"), index=True
    )
    # Who posted the fit, kept as text so it survives the fit being deleted.
    source_username: Mapped[str | None] = mapped_column(String(30))
    category: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(100))
    brand: Mapped[str | None] = mapped_column(String(100))
    color: Mapped[str | None] = mapped_column(String(50))
    url: Mapped[str | None] = mapped_column(String(2048))
    image_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("images.id", ondelete="SET NULL"))
    pin_x: Mapped[float | None] = mapped_column(Float)
    pin_y: Mapped[float | None] = mapped_column(Float)
    zoom: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # Saved from a styled look a friend sent in chat: that message and the piece's place in it.
    look_message_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), index=True
    )
    look_index: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )

    image = relationship("Image", lazy="joined")
