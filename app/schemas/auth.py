from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    client: Literal["web", "native"] = Field(
        default="web",
        description=(
            '`"web"`: the refresh token is set as an HttpOnly cookie. `"native"` (iOS/Android '
            "apps): it's returned in the response body instead, and no cookie is set."
        ),
    )

    model_config = ConfigDict(
        json_schema_extra={"examples": [{"email": "jane@example.com", "password": "s3cure-passw0rd"}]}
    )


class RefreshRequest(BaseModel):
    """Native apps send their refresh token in the body. Browsers send the cookie and no body."""

    refresh_token: str = Field(min_length=1)


class Token(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    # Native clients only. Web clients get the refresh token as a cookie, and these are omitted.
    refresh_token: str | None = None
    refresh_expires_in: int | None = None
