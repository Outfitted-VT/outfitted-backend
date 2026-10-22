import uuid

from sqlalchemy import JSON, ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin


class ImageDetection(TimestampMixin, Base):
    """The clothing pieces detected in an image, kept so repeat requests are free and the raw
    results stay available for later features (search, recommendations)."""

    __tablename__ = "image_detections"
    # Counting a user's detections in the last day enforces the daily limit.
    __table_args__ = (Index("ix_image_detections_user_id_created_at", "user_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    # One detection per image: images can't change after upload.
    image_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("images.id", ondelete="CASCADE"), unique=True
    )
    model: Mapped[str] = mapped_column(String(100))
    # {"items": [...], "occasion_tags": [...], "style_tags": [...]}, as returned by the API.
    result: Mapped[dict] = mapped_column(JSON)
