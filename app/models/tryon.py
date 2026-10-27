import uuid

from sqlalchemy import ForeignKey, Index, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin
from app.models.image import Image


class TryOn(TimestampMixin, Base):
    """A generated virtual try-on: the user's photo wearing either a whole outfit from one
    photo (`outfit_image`) or separate pieces from several photos (`pieces`)."""

    __tablename__ = "tryons"
    # Counting a user's try-ons in the last day enforces the daily limit.
    __table_args__ = (Index("ix_tryons_user_id_created_at", "user_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    # Images can be deleted independently (e.g. with a fit), so the try-on keeps its row
    # for the daily limit and just loses the reference.
    person_image_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("images.id", ondelete="SET NULL")
    )
    outfit_image_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("images.id", ondelete="SET NULL")
    )
    result_image_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("images.id", ondelete="SET NULL")
    )
    # Which model generated it, e.g. "gemini-3.1-flash-image".
    model: Mapped[str] = mapped_column(String(100))

    person_image: Mapped[Image | None] = relationship(foreign_keys=[person_image_id], lazy="joined")
    outfit_image: Mapped[Image | None] = relationship(foreign_keys=[outfit_image_id], lazy="joined")
    result_image: Mapped[Image | None] = relationship(foreign_keys=[result_image_id], lazy="joined")
    pieces: Mapped[list["TryOnPiece"]] = relationship(
        order_by="TryOnPiece.position", cascade="all, delete-orphan", lazy="selectin"
    )


class TryOnPiece(Base):
    """One clothing photo in a piece-by-piece try-on, and where it goes on the body."""

    __tablename__ = "tryon_pieces"

    tryon_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tryons.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    # "head", "top", "outerwear", "one_piece", "bottom", "feet", or "accessory".
    slot: Mapped[str] = mapped_column(String(20))
    image_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("images.id", ondelete="SET NULL"))

    image: Mapped[Image | None] = relationship(lazy="joined")
