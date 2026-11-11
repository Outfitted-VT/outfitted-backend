"""Fit votes — viewers' answers to a fit's poll ("Would you wear it?" unless the poster
picked another question).

One vote per viewer per fit: voting again replaces the previous answer, and
retracting removes it. Both operations are idempotent.
"""

import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.user import User
from app.repositories import vote as vote_repository
from app.services import notification as notifications
from app.services.fit import get_fit


class NoPollError(Exception):
    """The fit was posted without a poll."""


class InvalidPollOptionError(Exception):
    """The answer index is past the end of the fit's poll."""


def cast_vote(db: Session, user: User, fit_id: uuid.UUID, option: int) -> None:
    """Record or change the user's vote. Raises FitNotFoundError, NoPollError or
    InvalidPollOptionError."""
    fit = get_fit(db, fit_id)
    if not fit.poll_options:
        raise NoPollError
    if option >= len(fit.poll_options):
        raise InvalidPollOptionError
    try:
        first = vote_repository.set_vote(db, user.id, fit_id, option)
        db.commit()
    except IntegrityError:
        # Another request inserted this user's first vote at the same moment.
        # The row exists now, so change it rather than inserting a second one.
        db.rollback()
        vote_repository.update_option(db, user.id, fit_id, option)
        db.commit()
        return
    if first:
        notifications.notify(db, fit.user_id, "fit_vote", actor=user, entity_type="fit", entity_id=fit.id)


def retract_vote(db: Session, user: User, fit_id: uuid.UUID) -> None:
    """Remove the user's vote. Raises FitNotFoundError. Idempotent."""
    get_fit(db, fit_id)
    vote_repository.remove_vote(db, user.id, fit_id)
    db.commit()
