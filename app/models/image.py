import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String, Uuid, false
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin


class Image(TimestampMixin, Base):
    __tablename__ = "images"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # Path within storage, e.g. "images/3f2a....webp". The public URL is built from it.
    storage_key: Mapped[str] = mapped_column(String(255), unique=True)
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    size_bytes: Mapped[int] = mapped_column(Integer)
    # True for AI-generated images (virtual try-on results), so clients can label them.
    generated: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
