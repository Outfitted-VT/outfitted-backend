import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin
from app.models.image import Image


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    username: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str | None] = mapped_column(String(100))
    bio: Mapped[str | None] = mapped_column(String(160))
    # use_alter: users and images reference each other, so this FK is added after both tables exist.
    avatar_image_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("images.id", ondelete="SET NULL", use_alter=True)
    )
    is_active: Mapped[bool] = mapped_column(default=True)

    # Closet privacy settings
    default_closet_privacy: Mapped[str] = mapped_column(String(20), default="public", server_default="public")

    style_tags: Mapped[list[str]] = mapped_column(JSON, default=list, server_default="[]")
    fit_preference: Mapped[str | None] = mapped_column(String(10))
    top_size: Mapped[str | None] = mapped_column(String(4))
    bottom_size: Mapped[str | None] = mapped_column(String(4))
    feedback_tone: Mapped[str | None] = mapped_column(String(10))

    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    timezone: Mapped[str] = mapped_column(String(64), default="UTC", server_default="UTC")

    avatar: Mapped[Image | None] = relationship(foreign_keys=[avatar_image_id], lazy="joined")
