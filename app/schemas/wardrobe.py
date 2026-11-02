import uuid
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from app.schemas.user import UtcDatetime


def _strip(v: str) -> str:
    return v.strip()


TrimmedStr = Annotated[str, AfterValidator(_strip)]
PrimaryCategory = Literal["shoes", "clothing", "accessories"]


class WardrobeItemCreate(BaseModel):
    primary_category: PrimaryCategory
    name: Annotated[TrimmedStr, Field(min_length=1, max_length=120, examples=["Retro Metallic Silver Runners"])]
    brand: Annotated[TrimmedStr, Field(max_length=100)] | None = None
    sub_category: Annotated[TrimmedStr, Field(max_length=50)] | None = None
    color: Annotated[TrimmedStr, Field(max_length=50)] | None = None
    price: float = Field(ge=0.0, default=0.0)
    times_worn: int = Field(ge=0, default=0)
    tag: Annotated[TrimmedStr, Field(max_length=80)] | None = None
    image_url: Annotated[TrimmedStr, Field(max_length=2048)] | None = None
    notes: str | None = None


class WardrobeItemUpdate(BaseModel):
    name: Annotated[TrimmedStr, Field(min_length=1, max_length=120)] | None = None
    brand: Annotated[TrimmedStr, Field(max_length=100)] | None = None
    primary_category: PrimaryCategory | None = None
    sub_category: Annotated[TrimmedStr, Field(max_length=50)] | None = None
    color: Annotated[TrimmedStr, Field(max_length=50)] | None = None
    price: float | None = Field(ge=0.0, default=None)
    times_worn: int | None = Field(ge=0, default=None)
    tag: Annotated[TrimmedStr, Field(max_length=80)] | None = None
    image_url: Annotated[TrimmedStr, Field(max_length=2048)] | None = None
    notes: str | None = None


class WardrobeItemRead(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    primary_category: str
    sub_category: str | None
    name: str
    brand: str | None
    color: str | None
    price: float
    times_worn: int
    cost_per_wear: float
    last_worn_at: UtcDatetime | None
    tag: str | None
    image_url: str | None
    notes: str | None
    created_at: UtcDatetime
    updated_at: UtcDatetime

    model_config = ConfigDict(from_attributes=True)


class WardrobeSummaryRead(BaseModel):
    total_pieces: int
    total_valuation: float
    average_cost_per_wear: float
    shoes_count: int
    clothing_count: int
    accessories_count: int
