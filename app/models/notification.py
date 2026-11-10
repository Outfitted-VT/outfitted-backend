import uuid
from datetime import datetime, time

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, String, Time, Uuid, func, true
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import utcnow

NOTIFICATION_TYPES = (
    "follow",
    "like",
    "comment",
    "fit_vote",
    "fit_check_vote",
    "story_reply",
    "story_view_milestone",
    "circle_added",
    "message",
    "streak_reminder",
    "streak_milestone",
    "streak_saved",
    "streak_lost",
)


class Notification(Base):
    """One in-app notification. Grouped types (likes, votes, story views) merge into one row per item,
    and created_at moves forward when someone new joins it."""

    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notifications_user_id_created_at", "user_id", "created_at"),
        Index("ix_notifications_user_id_read_at", "user_id", "read_at"),
        Index("ix_notifications_user_id_group_key", "user_id", "group_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    type: Mapped[str] = mapped_column(String(30))
    entity_type: Mapped[str | None] = mapped_column(String(20))
    entity_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    group_key: Mapped[str | None] = mapped_column(String(100))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )


class NotificationSettings(Base):
    """Push preferences per type group. Quiet hours are local times in the user's timezone."""

    __tablename__ = "notification_settings"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    social: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    messages: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    stories: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    streaks: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    quiet_hours_start: Mapped[time | None] = mapped_column(Time)
    quiet_hours_end: Mapped[time | None] = mapped_column(Time)
