import json
import uuid

from sqlalchemy import ForeignKey, Index, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin


class OutfitMemory(TimestampMixin, Base):
    """
    A daily logged outfit memory in the user's fashion calendar.
    Records date, reflection notes, weather, rating, and tagged wardrobe pieces.
    """

    __tablename__ = "outfit_memories"
    __table_args__ = (
        Index("ix_outfit_memories_user_date", "user_id", "date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)

    date: Mapped[str] = mapped_column(String(10), index=True)  # YYYY-MM-DD
    title: Mapped[str] = mapped_column(String(150))
    photo_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    weather: Mapped[str | None] = mapped_column(String(100), nullable=True)
    rating: Mapped[int] = mapped_column(Integer, default=5, server_default="5")

    _tagged_pieces: Mapped[str] = mapped_column("tagged_pieces", Text, default="[]", server_default="[]")

    user = relationship("User", lazy="joined")

    @property
    def tagged_pieces(self) -> list[str]:
        if not self._tagged_pieces:
            return []
        try:
            return json.loads(self._tagged_pieces)
        except Exception:
            return []

    @tagged_pieces.setter
    def tagged_pieces(self, val: list[str] | None) -> None:
        self._tagged_pieces = json.dumps(val or [])
