import uuid
from datetime import time
from typing import Self

from pydantic import BaseModel, Field, model_validator

from app.schemas.user import UserSummary, UtcDatetime


class NotificationRead(BaseModel):
    id: uuid.UUID
    type: str
    actor: UserSummary | None = Field(description="The most recent person behind it, if any.")
    actors: list[UserSummary] = Field(description="Up to the 2 most recent people, for grouped rows.")
    actor_count: int = Field(description="How many different people a grouped row covers.")
    entity_type: str | None
    entity_id: uuid.UUID | None
    title: str
    body: str
    link: str = Field(description='App route to open, e.g. "/fits/<id>" or "/conversations/<id>".')
    data: dict
    read: bool
    created_at: UtcDatetime


class UnreadCount(BaseModel):
    unread: int


class MarkRead(BaseModel):
    ids: list[uuid.UUID] | None = Field(default=None, max_length=200)
    all: bool = False

    @model_validator(mode="after")
    def one_of(self) -> Self:
        if self.all == (self.ids is not None):
            raise ValueError("Send either ids or all=true")
        return self


class NotificationSettingsRead(BaseModel):
    social: bool = True
    messages: bool = True
    stories: bool = True
    streaks: bool = True
    quiet_hours_start: time | None = Field(default=None, description='Local time, e.g. "22:00".')
    quiet_hours_end: time | None = Field(default=None, description='Local time, e.g. "07:30".')
    timezone: str


class NotificationSettingsUpdate(BaseModel):
    social: bool | None = None
    messages: bool | None = None
    stories: bool | None = None
    streaks: bool | None = None
    quiet_hours_start: time | None = None
    quiet_hours_end: time | None = None

    @model_validator(mode="after")
    def quiet_hours_together(self) -> Self:
        fields = self.model_fields_set & {"quiet_hours_start", "quiet_hours_end"}
        if fields and (len(fields) == 1 or (self.quiet_hours_start is None) != (self.quiet_hours_end is None)):
            raise ValueError("Send quiet_hours_start and quiet_hours_end together (both times, or both null)")
        return self
