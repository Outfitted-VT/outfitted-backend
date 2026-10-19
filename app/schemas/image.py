import uuid

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.storage import media_url


class ImageRead(BaseModel):
    id: uuid.UUID
    width: int
    height: int
    storage_key: str = Field(exclude=True)

    model_config = ConfigDict(from_attributes=True)

    @computed_field
    @property
    def url(self) -> str:
        return media_url(self.storage_key)
