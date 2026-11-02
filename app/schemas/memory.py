import uuid
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from app.schemas.user import UtcDatetime


def _strip(v: str) -> str:
    return v.strip()


TrimmedStr = Annotated[str, AfterValidator(_strip)]


class OutfitMemoryCreate(BaseModel):
    date: Annotated[TrimmedStr, Field(min_length=10, max_length=10, pattern=r"^\d{4}-\d{2}-\d{2}$", examples=["2026-11-02"])]
    title: Annotated[TrimmedStr, Field(min_length=1, max_length=150, examples=["Monday Studio Critique"])]
    photo_url: Annotated[TrimmedStr, Field(max_length=2048)] | None = None
    notes: str | None = None
    weather: Annotated[TrimmedStr, Field(max_length=100)] | None = None
    rating: int = Field(ge=1, le=5, default=5)
    tagged_pieces: list[str] = Field(default_factory=list)
    auto_log_wear: bool = True


class OutfitMemoryRead(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    date: str
    title: str
    photo_url: str | None
    notes: str | None
    weather: str | None
    rating: int
    tagged_pieces: list[str]
    created_at: UtcDatetime
    updated_at: UtcDatetime

    model_config = ConfigDict(from_attributes=True)
