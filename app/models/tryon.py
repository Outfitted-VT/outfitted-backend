import uuid

from sqlalchemy import ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin
from app.models.image import Image


class TryOn(TimestampMixin, Base):
    """A generated virtual try-on: the user's photo wearing an outfit from another photo."""

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
