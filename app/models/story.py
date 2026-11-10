import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import utcnow
from app.models.image import Image
from app.models.user import User

STORY_VISIBILITIES = ("public", "close_friends")


class Story(Base):
    """A photo shared for 24 hours. Optionally links to one of the author's fits."""

    __tablename__ = "stories"
    __table_args__ = (Index("ix_stories_user_id_expires_at", "user_id", "expires_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    image_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("images.id", ondelete="CASCADE"))
    caption: Mapped[str | None] = mapped_column(String(200))
    fit_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("fits.id", ondelete="SET NULL"))
    visibility: Mapped[str] = mapped_column(String(20), default="public", server_default="public")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    author: Mapped[User] = relationship(lazy="joined")
    image: Mapped[Image] = relationship(lazy="joined")


class StoryView(Base):
    """Who saw a story, once per viewer."""

    __tablename__ = "story_views"
    __table_args__ = (Index("ix_story_views_story_id_viewed_at", "story_id", "viewed_at"),)

    story_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("stories.id", ondelete="CASCADE"), primary_key=True
    )
    viewer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    viewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )

    viewer: Mapped[User] = relationship(lazy="joined")
