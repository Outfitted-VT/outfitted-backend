import uuid

from sqlalchemy import Float, ForeignKey, Index, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin
from app.models.image import Image
from app.models.user import User


class Fit(TimestampMixin, Base):
    """An outfit post: photos, a caption, and the clothing items in it."""

    __tablename__ = "fits"
    # Feeds list fits newest first, overall and per user.
    __table_args__ = (
        Index("ix_fits_created_at_id", "created_at", "id"),
        Index("ix_fits_user_id_created_at_id", "user_id", "created_at", "id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    caption: Mapped[str | None] = mapped_column(Text)

    author: Mapped[User] = relationship()
    fit_images: Mapped[list["FitImage"]] = relationship(
        order_by="FitImage.position", cascade="all, delete-orphan"
    )
    items: Mapped[list["FitItem"]] = relationship(
        order_by="FitItem.position", cascade="all, delete-orphan"
    )

    @property
    def images(self) -> list[Image]:
        return [fit_image.image for fit_image in self.fit_images]


class FitImage(Base):
    """A photo in a fit, in display order. Each uploaded image can be in at most one fit."""

    __tablename__ = "fit_images"

    fit_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fits.id", ondelete="CASCADE"), primary_key=True
    )
    image_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("images.id", ondelete="CASCADE"), primary_key=True, unique=True
    )
    position: Mapped[int] = mapped_column(Integer)

    image: Mapped[Image] = relationship(lazy="joined")


class FitItem(Base):
    """A clothing item tagged in a fit, optionally pinned to a spot on one of its photos."""

    __tablename__ = "fit_items"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    fit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fits.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    category: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(100))
    brand: Mapped[str | None] = mapped_column(String(100))
    color: Mapped[str | None] = mapped_column(String(50))
    url: Mapped[str | None] = mapped_column(String(2048))
    # Pin position as fractions of the photo's width/height (0-1), so it survives resizing.
    pin_image_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("images.id", ondelete="SET NULL")
    )
    pin_x: Mapped[float | None] = mapped_column(Float)
    pin_y: Mapped[float | None] = mapped_column(Float)
