import uuid

from pydantic import BaseModel, Field

from app.schemas.user import UserSummary, UtcDatetime


class MessageCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=4000, description="Message text or advice.")
    fit_id: uuid.UUID | None = Field(default=None, description="Optional attached Fit ID.")


class MessageRead(BaseModel):
    id: uuid.UUID
    sender: UserSummary
    recipient: UserSummary
    content: str
    fit_id: uuid.UUID | None = None
    created_at: UtcDatetime
    read_at: UtcDatetime | None = None

    @classmethod
    def from_model(cls, message) -> "MessageRead":
        return cls(
            id=message.id,
            sender=UserSummary.model_validate(message.sender),
            recipient=UserSummary.model_validate(message.recipient),
            content=message.content,
            fit_id=message.fit_id,
            created_at=message.created_at,
            read_at=message.read_at,
        )


class MessageThreadRead(BaseModel):
    partner: UserSummary
    last_message: MessageRead
    unread_count: int
