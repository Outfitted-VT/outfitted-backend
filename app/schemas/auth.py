from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr


class LoginRequest(BaseModel):
    email: EmailStr
    password: str

    model_config = ConfigDict(
        json_schema_extra={"examples": [{"email": "jane@example.com", "password": "s3cure-passw0rd"}]}
    )


class Token(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
