import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin


class WardrobeItem(TimestampMixin, Base):
    """
    A standalone piece in the user's digital wardrobe (Shoes, Clothing, or Accessories).
    Tracks purchase price, wear count, and calculates real-time cost-per-wear.
    """

    __tablename__ = "wardrobe_items"
    __table_args__ = (
        Index("ix_wardrobe_items_user_category", "user_id", "primary_category"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)

    # Core FashionCarousel pillars: "shoes", "clothing", "accessories"
    primary_category: Mapped[str] = mapped_column(String(30), index=True)
    sub_category: Mapped[str | None] = mapped_column(String(50), nullable=True)

    name: Mapped[str] = mapped_column(String(120))
    brand: Mapped[str | None] = mapped_column(String(100), nullable=True)
    color: Mapped[str | None] = mapped_column(String(50), nullable=True)
    price: Mapped[float] = mapped_column(Float, default=0.0)
    times_worn: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_worn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    tag: Mapped[str | None] = mapped_column(String(80), nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    user = relationship("User", lazy="joined")

    @property
    def cost_per_wear(self) -> float:
        if self.times_worn > 0:
            return round(self.price / self.times_worn, 2)
        return float(self.price)
