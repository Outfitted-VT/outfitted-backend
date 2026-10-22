import uuid
from enum import StrEnum
from typing import Annotated, Literal, Self

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
MAX_TAGS_PER_KIND = 10


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


ItemSource = Literal["user", "detected"]
ShortText = Annotated[str | None, Field(max_length=50), OptionalText]


class FitItemIn(BaseModel):
    category: ItemCategory
    name: Annotated[str, AfterValidator(_strip), Field(min_length=1, max_length=100)]
    brand: Annotated[str | None, Field(max_length=100), OptionalText] = None
    color: ShortText = None
    pattern: ShortText = None
    material: ShortText = None
    silhouette: ShortText = Field(default=None, description='How it fits, e.g. "oversized".')
    url: HttpUrl | None = Field(default=None, description="Where to buy it.")
    pin: ItemPin | None = None
    source: ItemSource = Field(
        default="user",
        description='"detected" for items from `POST /detections` (keep it when the user edits '
        'one), "user" for items a person entered.',
    )


class FitItemRead(BaseModel):
    id: uuid.UUID
    category: ItemCategory
    name: str
    brand: str | None
    color: str | None
    pattern: str | None
    material: str | None
    silhouette: str | None
    url: str | None
    pin: ItemPin | None
    source: ItemSource

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
            pattern=item.pattern,
            material=item.material,
            silhouette=item.silhouette,
            url=item.url,
            pin=pin,
            source=item.source,
        )


Caption = Annotated[str | None, Field(max_length=2200), OptionalText]
Items = Annotated[list[FitItemIn], Field(max_length=MAX_ITEMS_PER_FIT)]


def _normalize_tag(value: str) -> str:
    return " ".join(value.split()).lower()


def _dedupe(tags: list[str]) -> list[str]:
    return list(dict.fromkeys(tags))


Tag = Annotated[str, AfterValidator(_normalize_tag), Field(min_length=1, max_length=30)]
Tags = Annotated[list[Tag], Field(max_length=MAX_TAGS_PER_KIND), AfterValidator(_dedupe)]


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
    occasion_tags: Tags = Field(default=[], description='Where to wear it, e.g. "date night".')
    style_tags: Tags = Field(default=[], description='The style, e.g. "streetwear".')

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
    occasion_tags: Tags | None = Field(default=None, description="Replaces them when sent.")
    style_tags: Tags | None = Field(default=None, description="Replaces them when sent.")

    @field_validator("items", "occasion_tags", "style_tags")
    @classmethod
    def lists_not_null(cls, values: list | None) -> list:
        if values is None:
            raise ValueError("Send an empty list to remove them all")
        return values


class FitRead(BaseModel):
    id: uuid.UUID
    author: UserSummary
    caption: str | None
    images: list[ImageRead]
    items: list[FitItemRead]
    occasion_tags: list[str]
    style_tags: list[str]
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
            occasion_tags=fit.occasion_tags,
            style_tags=fit.style_tags,
            like_count=view.like_count,
            liked_by_me=view.liked_by_me,
            saved_by_me=view.saved_by_me,
            created_at=fit.created_at,
        )
