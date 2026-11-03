import uuid
from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models.comment import FitComment


def add_comment(db: Session, fit_id: uuid.UUID, user_id: uuid.UUID, content: str) -> FitComment:
    comment = FitComment(fit_id=fit_id, user_id=user_id, content=content)
    db.add(comment)
    db.flush()
    return comment


def get_comment(db: Session, comment_id: uuid.UUID) -> FitComment | None:
    return db.get(FitComment, comment_id)


def list_comments(
    db: Session, fit_id: uuid.UUID, limit: int = 50
) -> list[FitComment]:
    return list(
        db.scalars(
            select(FitComment)
            .where(FitComment.fit_id == fit_id)
            .order_by(FitComment.created_at.asc(), FitComment.id.asc())
            .limit(limit)
        )
    )


def delete_comment(db: Session, comment_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    comment = db.get(FitComment, comment_id)
    if not comment or comment.user_id != user_id:
        return False
    db.delete(comment)
    db.flush()
    return True


def comment_counts(db: Session, fit_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not fit_ids:
        return {}
    rows = db.execute(
        select(FitComment.fit_id, func.count())
        .where(FitComment.fit_id.in_(fit_ids))
        .group_by(FitComment.fit_id)
    )
    return {fit_id: count for fit_id, count in rows}
