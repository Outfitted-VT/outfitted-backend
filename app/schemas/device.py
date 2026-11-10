from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.schemas.user import UtcDatetime

Token = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=512)]


class DeviceRegister(BaseModel):
    platform: Literal["ios", "android"]
    token: Token = Field(description="APNs device token (hex) on iOS, FCM registration token on Android.")
    app_version: Annotated[str | None, Field(max_length=32)] = None


class DeviceRead(BaseModel):
    platform: str
    token: str
    app_version: str | None
    created_at: UtcDatetime
    last_seen_at: UtcDatetime

    model_config = ConfigDict(from_attributes=True)
