from typing import Literal, Self

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

INSECURE_DEV_SECRET_KEY = "dev-only-insecure-secret-key-change-me"


class Settings(BaseSettings):
    PROJECT_NAME: str = "Outfitted API"
    VERSION: str = "0.1.0"
    ENVIRONMENT: str = "development"
    API_V1_PREFIX: str = "/api/v1"
    CORS_ORIGINS: list[str] = ["http://localhost:3000"]
    DATABASE_URL: str = "sqlite:///./outfitted.db"

    # Uploaded files. MEDIA_BASE_URL is where clients load them from (a CDN/bucket URL later).
    MEDIA_ROOT: str = "media"
    MEDIA_BASE_URL: str = "http://localhost:8000/media"
    MAX_UPLOAD_BYTES: int = 10 * 1024 * 1024

    SECRET_KEY: str = INSECURE_DEV_SECRET_KEY
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # The refresh token is sent as an HttpOnly cookie. Secure cookies are only sent over HTTPS
    # (browsers make an exception for http://localhost). Use SameSite "none" only if the
    # frontend and API are on different sites (e.g. app.vercel.app and api.onrender.com).
    REFRESH_COOKIE_SECURE: bool = True
    REFRESH_COOKIE_SAMESITE: Literal["lax", "strict", "none"] = "lax"

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True)

    @field_validator("DATABASE_URL")
    @classmethod
    def use_psycopg_driver(cls, url: str) -> str:
        # Hosting providers hand out postgres:// or postgresql:// URLs, which SQLAlchemy
        # maps to psycopg2. Point them at psycopg (v3), the driver we install.
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url.removeprefix(prefix)
        return url

    @model_validator(mode="after")
    def require_real_secret_outside_development(self) -> Self:
        # Anyone who knows the secret key can forge login tokens for any user.
        if self.ENVIRONMENT != "development" and (
            self.SECRET_KEY == INSECURE_DEV_SECRET_KEY or len(self.SECRET_KEY) < 32
        ):
            raise ValueError("SECRET_KEY must be set to at least 32 characters outside development")
        return self

    @model_validator(mode="after")
    def samesite_none_requires_secure(self) -> Self:
        # Browsers reject SameSite=None cookies that aren't also Secure.
        if self.REFRESH_COOKIE_SAMESITE == "none" and not self.REFRESH_COOKIE_SECURE:
            raise ValueError("REFRESH_COOKIE_SAMESITE=none requires REFRESH_COOKIE_SECURE=true")
        return self

    @property
    def refresh_cookie_path(self) -> str:
        # Only send the refresh cookie to auth endpoints, not on every API request.
        return f"{self.API_V1_PREFIX}/auth"


settings = Settings()
