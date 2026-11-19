import uuid

from pydantic import BaseModel, Field

from app.schemas.image import ImageRead
from app.schemas.user import UserSummary, UtcDatetime


class LookPiecePin(BaseModel):
    x: float
    y: float


class LookPieceRead(BaseModel):
    """A piece of a styled look. Show `photo` whole, or with `zoom` enlarged and centred on `pin`."""

    category: str
    name: str
    brand: str | None = None
    color: str | None = None
    url: str | None = None
    photo: ImageRead | None = None
    pin: LookPiecePin | None = None
    zoom: bool = False
    fit_id: uuid.UUID | None = None
    source_username: str | None = None


class SavedLookRead(BaseModel):
    """A styled look you saved from chat (Style a Friend)."""

    id: uuid.UUID
    message_id: uuid.UUID | None = Field(description="The look message; `null` once it's deleted.")
    conversation_id: uuid.UUID | None
    stylist: UserSummary | None = Field(description="Who styled it; `null` if their account is gone.")
    note: str | None
    tryon_image: ImageRead | None
    pieces: list[LookPieceRead]
    created_at: UtcDatetime
