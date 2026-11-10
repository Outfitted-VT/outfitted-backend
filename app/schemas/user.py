import re
import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core.localtime import is_valid_timezone
from app.schemas.image import ImageRead

USERNAME_PATTERN = re.compile(r"^[a-z0-9_.]{3,30}$")
# Names that would clash with routes (/users/me) or be used to impersonate staff.
RESERVED_USERNAMES = {
    "me", "search", "suggestions", "admin", "administrator", "api", "auth", "explore", "feed", "help", "login",
    "logout", "outfitted", "root", "settings", "signup", "staff", "support", "system",
}


def _validate_username(value: str) -> str:
    value = value.strip().lower()
    if not USERNAME_PATTERN.fullmatch(value):
        raise ValueError(
            "Username must be 3-30 characters: lowercase letters, numbers, underscores, and periods"
        )
    if value.startswith(".") or value.endswith(".") or ".." in value:
        raise ValueError("Username can't start or end with a period, or contain '..'")
    if value in RESERVED_USERNAMES:
        raise ValueError("This username is reserved")
    return value


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip() or None


def _validate_timezone(value: str) -> str:
    if not is_valid_timezone(value):
        raise ValueError('Timezone must be an IANA name such as "America/New_York"')
    return value


Username = Annotated[str, AfterValidator(_validate_username)]
Timezone = Annotated[str, Field(max_length=64), AfterValidator(_validate_timezone)]
OptionalText = AfterValidator(_blank_to_none)


def _assume_utc(value: datetime) -> datetime:
    # SQLite drops timezone info; timestamps are always stored in UTC.
    return value if value.tzinfo else value.replace(tzinfo=UTC)


UtcDatetime = Annotated[datetime, AfterValidator(_assume_utc)]

StyleTag = Literal["minimal", "tailored", "streetwear", "y2k", "romantic", "sporty"]
FitPreference = Literal["fitted", "true", "relaxed"]
Size = Literal["XS", "S", "M", "L", "XL"]
FeedbackTone = Literal["honest", "kind", "hype"]


class UserCreate(BaseModel):
    email: EmailStr
    username: Username
    password: str = Field(min_length=8, max_length=128)
    full_name: Annotated[str | None, Field(max_length=100), OptionalText] = None

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "email": "jane@example.com",
                    "username": "jane.doe",
                    "password": "s3cure-passw0rd",
                    "full_name": "Jane Doe",
                }
            ]
        }
    )

    @field_validator("email")
    @classmethod
    def normalize_email(cls, email: str) -> str:
        return email.lower()


class UserUpdate(BaseModel):
    """Fields to change on your own profile. Omitted fields are left unchanged; send null to clear."""

    username: Username | None = None
    full_name: Annotated[str | None, Field(max_length=100), OptionalText] = None
    bio: Annotated[str | None, Field(max_length=160), OptionalText] = None
    avatar_image_id: uuid.UUID | None = None
    style_tags: list[StyleTag] | None = Field(default=None, max_length=3)
    fit_preference: FitPreference | None = None
    top_size: Size | None = None
    bottom_size: Size | None = None
    feedback_tone: FeedbackTone | None = None
    timezone: Timezone | None = Field(default=None, description="IANA name from the device; streak days follow it.")

    @field_validator("style_tags")
    @classmethod
    def unique_style_tags(cls, tags: list[str] | None) -> list[str] | None:
        return list(dict.fromkeys(tags)) if tags is not None else None

    @field_validator("username")
    @classmethod
    def username_not_null(cls, username: str | None) -> str:
        # Only runs when the field is sent; omitting it is fine, clearing it isn't.
        if username is None:
            raise ValueError("Username can't be removed")
        return username


class UserSummary(BaseModel):
    """Compact author info embedded in fits, follower lists, etc."""

    id: uuid.UUID
    username: str
    full_name: str | None
    avatar: ImageRead | None

    model_config = ConfigDict(from_attributes=True)


class UserSearchResult(UserSummary):
    """Result when searching for users/friends."""

    bio: str | None = None
    is_following: bool = False


class UserSuggestion(UserSummary):
    """Someone you might want in your circle."""

    mutual_count: int = Field(description="People you follow who follow them.")


class UserRead(UserSummary):
    """Your own account, including private fields like email."""

    email: EmailStr
    bio: str | None
    is_active: bool
    created_at: UtcDatetime
    style_tags: list[str] = []
    fit_preference: str | None = None
    top_size: str | None = None
    bottom_size: str | None = None
    feedback_tone: str | None = None
    timezone: str = "UTC"
    current_streak: int = 0

    @field_validator("style_tags", mode="before")
    @classmethod
    def none_to_empty(cls, tags: list[str] | None) -> list[str]:
        return tags or []


class ProfileRead(UserSummary):
    """Someone's public profile."""

    bio: str | None
    fit_count: int
    follower_count: int
    following_count: int
    is_following: bool = Field(description="Whether you follow this user.")
    created_at: UtcDatetime
    current_streak: int = 0

    @classmethod
    def from_view(cls, view) -> "ProfileRead":
        user = view.user
        return cls(
            id=user.id,
            username=user.username,
            full_name=user.full_name,
            avatar=ImageRead.model_validate(user.avatar) if user.avatar else None,
            bio=user.bio,
            fit_count=view.fit_count,
            follower_count=view.follower_count,
            following_count=view.following_count,
            is_following=view.is_following,
            created_at=user.created_at,
            current_streak=view.current_streak,
        )


class UserPrivacySettingsRead(BaseModel):
    default_closet_privacy: str = 'public'

    model_config = ConfigDict(from_attributes=True)


class UserPrivacySettingsUpdate(BaseModel):
    default_closet_privacy: str | None = None
