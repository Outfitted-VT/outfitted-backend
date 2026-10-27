import uuid
from datetime import datetime
from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from app.schemas.image import ImageRead


class PieceSlot(StrEnum):
    """Where a piece goes on the body, from head to feet."""

    HEAD = "head"
    TOP = "top"
    OUTERWEAR = "outerwear"
    ONE_PIECE = "one_piece"
    BOTTOM = "bottom"
    FEET = "feet"
    ACCESSORY = "accessory"


# Head to toe; pieces are sent to the model in this order.
SLOT_ORDER = list(PieceSlot)


class TryOnPieceIn(BaseModel):
    slot: PieceSlot
    image_id: uuid.UUID = Field(description="A photo of the piece, uploaded with `POST /images`.")


class TryOnCreate(BaseModel):
    """Send `outfit_image_id` to try on a whole outfit from one photo, or `pieces` to
    combine separate pieces from several photos. Exactly one of the two."""

    person_image_id: uuid.UUID
    outfit_image_id: uuid.UUID | None = Field(
        default=None, description="Whole-outfit mode: one photo of the full outfit."
    )
    pieces: list[TryOnPieceIn] | None = Field(
        default=None,
        min_length=1,
        max_length=len(PieceSlot),
        description="Pieces mode: one photo per slot (head, top, outerwear, ...).",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "person_image_id": "517830fe-d102-41c1-84b5-f7036e814611",
                    "outfit_image_id": "16cc86b0-3f41-48af-b5b2-1ba3a3e36c26",
                },
                {
                    "person_image_id": "517830fe-d102-41c1-84b5-f7036e814611",
                    "pieces": [
                        {"slot": "top", "image_id": "16cc86b0-3f41-48af-b5b2-1ba3a3e36c26"},
                        {"slot": "bottom", "image_id": "9b2e4c1a-5d3f-4e8a-b7c6-0a1f2e3d4c5b"},
                        {"slot": "feet", "image_id": "c4d5e6f7-a8b9-4c0d-9e1f-2a3b4c5d6e7f"},
                    ],
                },
            ]
        }
    )

    @model_validator(mode="after")
    def check_mode(self) -> Self:
        if (self.outfit_image_id is None) == (self.pieces is None):
            raise ValueError("Send either outfit_image_id or pieces, not both")
        if self.pieces is None:
            return self

        slots = [piece.slot for piece in self.pieces]
        if len(set(slots)) != len(slots):
            raise ValueError("Each slot can only be used once")
        image_ids = [piece.image_id for piece in self.pieces]
        if len(set(image_ids)) != len(image_ids):
            raise ValueError("Each image can only be used once")
        if PieceSlot.ONE_PIECE in slots and ({PieceSlot.TOP, PieceSlot.BOTTOM} & set(slots)):
            raise ValueError("A one_piece can't be combined with a top or bottom")
        # Head to toe, so the model sees them in a consistent order.
        self.pieces.sort(key=lambda piece: SLOT_ORDER.index(piece.slot))
        return self


class TryOnPieceRead(BaseModel):
    slot: PieceSlot
    image: ImageRead | None = Field(description="`null` if the image was deleted later.")

    model_config = ConfigDict(from_attributes=True)


class TryOnRead(BaseModel):
    id: uuid.UUID
    # The generated photo. Post it with POST /fits using result_image.id.
    result_image: ImageRead | None
    person_image: ImageRead | None
    # Whole-outfit mode only; `null` in pieces mode or if the image was deleted.
    outfit_image: ImageRead | None
    # Pieces mode only, head to toe; empty in whole-outfit mode.
    pieces: list[TryOnPieceRead]
    model: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    @computed_field
    @property
    def mode(self) -> Literal["outfit", "pieces"]:
        return "pieces" if self.pieces else "outfit"
