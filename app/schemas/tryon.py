import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.schemas.image import ImageRead


class TryOnCreate(BaseModel):
    person_image_id: uuid.UUID
    outfit_image_id: uuid.UUID

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "person_image_id": "517830fe-d102-41c1-84b5-f7036e814611",
                    "outfit_image_id": "16cc86b0-3f41-48af-b5b2-1ba3a3e36c26",
                }
            ]
        }
    )


class TryOnRead(BaseModel):
    id: uuid.UUID
    # The generated photo. Post it with POST /fits using result_image.id.
    result_image: ImageRead | None
    person_image: ImageRead | None
    outfit_image: ImageRead | None
    model: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True, protected_namespaces=())
