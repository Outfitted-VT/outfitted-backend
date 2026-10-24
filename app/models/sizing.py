import uuid

from sqlalchemy import Boolean, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin


class UserReferenceGarment(TimestampMixin, Base):
    """
    A clothing item the user already owns and loves the fit of (e.g. Levi's 501 in 30W, Zara M).
    Used as ground-truth anchor for the TrueSize Passport cross-brand translation.
    """

    __tablename__ = "user_reference_garments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    brand: Mapped[str] = mapped_column(String(80), index=True)
    category: Mapped[str] = mapped_column(String(30), index=True)  # "tops", "bottoms", "dresses", "outerwear", "shoes"
    item_name: Mapped[str] = mapped_column(String(120))  # e.g. "501 Original Fit Jeans"
    size: Mapped[str] = mapped_column(String(30))  # e.g. "30W 32L", "M", "US 8"
    fit_feeling: Mapped[str] = mapped_column(String(30), default="perfect", server_default="perfect")  # "perfect", "snug", "oversized"
    is_favorite: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
