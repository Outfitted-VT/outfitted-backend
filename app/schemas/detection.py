import uuid

from pydantic import BaseModel, ConfigDict

from app.schemas.fit import FitItemIn
from app.shopping import ProductMatch


class DetectionCreate(BaseModel):
    image_id: uuid.UUID

    model_config = ConfigDict(
        json_schema_extra={"examples": [{"image_id": "16cc86b0-3f41-48af-b5b2-1ba3a3e36c26"}]}
    )


class DetectedItem(FitItemIn):
    """A suggested piece. `url` is the best shop match; `matches` are the alternatives, best
    first. `POST /fits` ignores `matches`, so the item can be sent back as-is."""

    matches: list[ProductMatch] = []


class DetectionRead(BaseModel):
    """Suggested pieces and tags for a photo, in the shape `POST /fits` accepts."""

    image_id: uuid.UUID
    # Each has source "detected" and, when the model located it, a pin on this image.
    items: list[DetectedItem]
    occasion_tags: list[str]
    style_tags: list[str]
    model: str

    model_config = ConfigDict(protected_namespaces=())
