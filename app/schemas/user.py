import uuid
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=100)

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {"email": "jane@example.com", "password": "s3cure-passw0rd", "full_name": "Jane Doe"}
            ]
        }
    )

    @field_validator("email")
    @classmethod
    def normalize_email(cls, email: str) -> str:
        return email.lower()

    @field_validator("full_name")
    @classmethod
    def blank_name_to_none(cls, full_name: str | None) -> str | None:
        if full_name is None:
            return None
        return full_name.strip() or None


class UserRead(BaseModel):
    id: uuid.UUID
    email: EmailStr
    full_name: str | None
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @field_validator("created_at")
    @classmethod
    def assume_utc(cls, value: datetime) -> datetime:
        # SQLite drops timezone info; timestamps are always stored in UTC.
        return value if value.tzinfo else value.replace(tzinfo=UTC)
