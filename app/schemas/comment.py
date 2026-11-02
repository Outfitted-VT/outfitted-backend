import uuid

from pydantic import BaseModel, Field

from app.schemas.user import UserSummary, UtcDatetime


class FitCommentCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=2000, description="Comment or styling feedback text.")


class FitCommentRead(BaseModel):
    id: uuid.UUID
    fit_id: uuid.UUID
    author: UserSummary
    content: str
    created_at: UtcDatetime

    @classmethod
    def from_model(cls, comment) -> "FitCommentRead":
        return cls(
            id=comment.id,
            fit_id=comment.fit_id,
            author=UserSummary.model_validate(comment.author),
            content=comment.content,
            created_at=comment.created_at,
        )
