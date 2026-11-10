"""Comments on fits."""

import uuid

from sqlalchemy.orm import Session

from app.models.comment import FitComment
from app.models.user import User
from app.repositories import comment as comment_repository
from app.services import notification as notifications
from app.services.fit import get_fit


def add_comment(db: Session, author: User, fit_id: uuid.UUID, content: str) -> FitComment:
    """Raises FitNotFoundError."""
    fit = get_fit(db, fit_id)
    comment = comment_repository.add_comment(db, fit_id, author.id, content)
    db.commit()
    data = {"comment_id": str(comment.id), "preview": content}
    notifications.notify(db, fit.user_id, "comment", actor=author, entity_type="fit", entity_id=fit.id, data=data)
    return comment
