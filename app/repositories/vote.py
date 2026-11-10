"""Database access for fit votes. Queries only: no business rules, and never commits."""

import uuid

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.models.vote import FitVote


def set_vote(db: Session, user_id: uuid.UUID, fit_id: uuid.UUID, choice: str) -> bool:
    """Record the vote, replacing the user's previous one on this fit. True for a first vote.

    Raises IntegrityError if another request inserted this user's first vote
    between the UPDATE and the INSERT; the caller recovers with update_choice.
    """
    first = not update_choice(db, user_id, fit_id, choice)
    if first:
        db.add(FitVote(user_id=user_id, fit_id=fit_id, choice=choice))
    db.flush()
    return first


def update_choice(db: Session, user_id: uuid.UUID, fit_id: uuid.UUID, choice: str) -> bool:
    """Change an existing vote. False when the user hasn't voted on this fit."""
    result = db.execute(
        update(FitVote)
        .where(FitVote.user_id == user_id, FitVote.fit_id == fit_id)
        .values(choice=choice)
    )
    return result.rowcount > 0


def remove_vote(db: Session, user_id: uuid.UUID, fit_id: uuid.UUID) -> None:
    db.execute(delete(FitVote).where(FitVote.user_id == user_id, FitVote.fit_id == fit_id))


def vote_counts(db: Session, fit_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict[str, int]]:
    """{fit_id: {"wear": n, "rethink": n}} — choices with no votes are left out."""
    rows = db.execute(
        select(FitVote.fit_id, FitVote.choice, func.count())
        .where(FitVote.fit_id.in_(fit_ids))
        .group_by(FitVote.fit_id, FitVote.choice)
    )
    counts: dict[uuid.UUID, dict[str, int]] = {}
    for fit_id, choice, count in rows:
        counts.setdefault(fit_id, {})[choice] = count
    return counts


def votes_by_user(
    db: Session, user_id: uuid.UUID, fit_ids: list[uuid.UUID]
) -> dict[uuid.UUID, str]:
    """{fit_id: choice} for the fits this user has voted on."""
    rows = db.execute(
        select(FitVote.fit_id, FitVote.choice).where(
            FitVote.user_id == user_id, FitVote.fit_id.in_(fit_ids)
        )
    )
    return {fit_id: choice for fit_id, choice in rows}
