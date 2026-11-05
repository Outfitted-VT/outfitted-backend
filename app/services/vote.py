"""Fit votes — the "wear it or rethink" verdict on a fit.

One vote per viewer per fit: voting again replaces the previous choice, and
retracting removes it. Both operations are idempotent.
"""

import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.user import User
from app.repositories import vote as vote_repository
from app.services.fit import get_fit


def cast_vote(db: Session, user: User, fit_id: uuid.UUID, choice: str) -> None:
    """Record or change the user's vote. Raises FitNotFoundError."""
    get_fit(db, fit_id)
    try:
        vote_repository.set_vote(db, user.id, fit_id, choice)
        db.commit()
    except IntegrityError:
        # Another request inserted this user's first vote at the same moment.
        # The row exists now, so change it rather than inserting a second one.
        db.rollback()
        vote_repository.update_choice(db, user.id, fit_id, choice)
        db.commit()


def retract_vote(db: Session, user: User, fit_id: uuid.UUID) -> None:
    """Remove the user's vote. Raises FitNotFoundError. Idempotent."""
    get_fit(db, fit_id)
    vote_repository.remove_vote(db, user.id, fit_id)
    db.commit()
