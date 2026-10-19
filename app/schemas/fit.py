import uuid
from enum import StrEnum
from typing import Annotated, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    field_validator,
    model_validator,
)

from app.schemas.image import ImageRead
from app.schemas.user import OptionalText, UserSummary, UtcDatetime

MAX_IMAGES_PER_FIT = 10
MAX_ITEMS_PER_FIT = 30


class ItemCategory(StrEnum):
    TOP = "top"
    BOTTOM = "bottom"
    DRESS = "dress"
    OUTERWEAR = "outerwear"
    SHOES = "shoes"
    BAG = "bag"
    ACCESSORY = "accessory"
    JEWELRY = "jewelry"
    HEADWEAR = "headwear"
    OTHER = "other"


def _strip(value: str) -> str:
    return value.strip()


class ItemPin(BaseModel):
    """Where an item appears on one of the fit's photos, as fractions of width/height."""

    image_id: uuid.UUID
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)


class FitItemIn(BaseModel):
    category: ItemCategory
    name: Annotated[str, AfterValidator(_strip), Field(min_length=1, max_length=100)]
    brand: Annotated[str | None, Field(max_length=100), OptionalText] = None
    color: Annotated[str | None, Field(max_length=50), OptionalText] = None
    url: HttpUrl | None = Field(default=None, description="Where to buy it.")
    pin: ItemPin | None = None


class FitItemRead(BaseModel):
    id: uuid.UUID
    category: ItemCategory
    name: str
    brand: str | None
    color: str | None
    url: str | None
    pin: ItemPin | None

    @classmethod
    def from_model(cls, item) -> "FitItemRead":
        pin = None
        if item.pin_image_id is not None:
            pin = ItemPin(image_id=item.pin_image_id, x=item.pin_x, y=item.pin_y)
        return cls(
            id=item.id,
            category=item.category,
            name=item.name,
            brand=item.brand,
            color=item.color,
            url=item.url,
            pin=pin,
        )


Caption = Annotated[str | None, Field(max_length=2200), OptionalText]
Items = Annotated[list[FitItemIn], Field(max_length=MAX_ITEMS_PER_FIT)]


def _check_pins(items: list[FitItemIn], image_ids: set[uuid.UUID]) -> None:
    for item in items:
        if item.pin is not None and item.pin.image_id not in image_ids:
            raise ValueError("Each item pin must reference one of the fit's images")


class FitCreate(BaseModel):
    image_ids: list[uuid.UUID] = Field(
        min_length=1,
        max_length=MAX_IMAGES_PER_FIT,
        description="Images from `POST /images`, in display order.",
    )
    caption: Caption = None
    items: Items = []

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "image_ids": ["6dd19d83-ad1c-4041-8f0f-a412ea95314b"],
                    "caption": "Sunday thrift haul",
                    "items": [
                        {
                            "category": "outerwear",
                            "name": "Oversized denim jacket",
                            "brand": "Levi's",
                            "color": "light wash",
                            "url": "https://example.com/jacket",
                            "pin": {
                                "image_id": "6dd19d83-ad1c-4041-8f0f-a412ea95314b",
                                "x": 0.42,
                                "y": 0.31,
                            },
                        }
                    ],
                }
            ]
        }
    )

    @field_validator("image_ids")
    @classmethod
    def no_duplicate_images(cls, image_ids: list[uuid.UUID]) -> list[uuid.UUID]:
        if len(set(image_ids)) != len(image_ids):
            raise ValueError("Each image can only appear once")
        return image_ids

    @model_validator(mode="after")
    def pins_reference_fit_images(self) -> Self:
        _check_pins(self.items, set(self.image_ids))
        return self


class FitUpdate(BaseModel):
    """Change the caption and/or replace the full list of items. Images can't be changed."""

    caption: Caption = None
    items: Items | None = Field(default=None, description="Replaces all items when sent.")

    @field_validator("items")
    @classmethod
    def items_not_null(cls, items: list[FitItemIn] | None) -> list[FitItemIn]:
        if items is None:
            raise ValueError("Send an empty list to remove all items")
        return items


class FitRead(BaseModel):
    id: uuid.UUID
    author: UserSummary
    caption: str | None
    images: list[ImageRead]
    items: list[FitItemRead]
    like_count: int
    liked_by_me: bool
    saved_by_me: bool
    created_at: UtcDatetime

    @classmethod
    def from_view(cls, view) -> "FitRead":
        fit = view.fit
        return cls(
            id=fit.id,
            author=UserSummary.model_validate(fit.author),
            caption=fit.caption,
            images=[ImageRead.model_validate(image) for image in fit.images],
            items=[FitItemRead.from_model(item) for item in fit.items],
            like_count=view.like_count,
            liked_by_me=view.liked_by_me,
            saved_by_me=view.saved_by_me,
            created_at=fit.created_at,
        )
