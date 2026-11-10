import uuid
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, Field

from app.core.config import settings
from app.schemas.conversation import CleanText
from app.schemas.image import ImageRead
from app.schemas.user import UserSummary, UtcDatetime

StoryVisibility = Literal["public", "close_friends"]


def _not_blank(value: str | None) -> str:
    if value is None:
        raise ValueError("Reply can't be empty")
    return value


class StoryCreate(BaseModel):
    image_id: uuid.UUID = Field(description="From `POST /images`; blur faces first with `POST /images/{id}/blur-faces`.")
    caption: Annotated[str | None, Field(max_length=200), CleanText] = None
    fit_id: uuid.UUID | None = Field(default=None, description="One of your fits (not in your vault).")
    visibility: StoryVisibility = "public"


class StoryRead(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    image: ImageRead
    caption: str | None
    fit_id: uuid.UUID | None
    visibility: str
    created_at: UtcDatetime
    expires_at: UtcDatetime
    seen: bool = Field(description="Whether you viewed it. Always true for your own stories.")
    view_count: int | None = Field(default=None, description="Owner only; null for other people's stories.")


class StoryGroup(BaseModel):
    user: UserSummary
    stories: list[StoryRead] = Field(description="Oldest first, in the order they were posted.")
    has_unseen: bool
    latest_at: UtcDatetime | None = Field(description="When their newest story was posted; null with no stories.")


class StoryViewerRead(BaseModel):
    user: UserSummary
    viewed_at: UtcDatetime


class StoryReplyCreate(BaseModel):
    body: Annotated[str, Field(min_length=1, max_length=settings.MESSAGE_MAX_LENGTH), CleanText, AfterValidator(_not_blank)]
    client_id: str | None = Field(default=None, max_length=64)
