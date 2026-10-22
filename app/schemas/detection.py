import uuid

from pydantic import BaseModel, ConfigDict

from app.schemas.fit import FitItemIn


class DetectionCreate(BaseModel):
    image_id: uuid.UUID

    model_config = ConfigDict(
        json_schema_extra={"examples": [{"image_id": "16cc86b0-3f41-48af-b5b2-1ba3a3e36c26"}]}
    )


class DetectionRead(BaseModel):
    """Suggested pieces and tags for a photo, in the shape `POST /fits` accepts."""

    image_id: uuid.UUID
    # Each has source "detected" and, when the model located it, a pin on this image.
    items: list[FitItemIn]
    occasion_tags: list[str]
    style_tags: list[str]
    model: str

    model_config = ConfigDict(protected_namespaces=())
