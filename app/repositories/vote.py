"""Database access for fit votes. Queries only: no business rules, and never commits."""

import uuid

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.models.vote import FitVote


def set_vote(db: Session, user_id: uuid.UUID, fit_id: uuid.UUID, option: int) -> bool:
    """Record the vote, replacing the user's previous one on this fit. True for a first vote.

    Raises IntegrityError if another request inserted this user's first vote
    between the UPDATE and the INSERT; the caller recovers with update_option.
    """
    first = not update_option(db, user_id, fit_id, option)
    if first:
        db.add(FitVote(user_id=user_id, fit_id=fit_id, option=option))
    db.flush()
    return first


def update_option(db: Session, user_id: uuid.UUID, fit_id: uuid.UUID, option: int) -> bool:
    """Change an existing vote. False when the user hasn't voted on this fit."""
    result = db.execute(
        update(FitVote)
        .where(FitVote.user_id == user_id, FitVote.fit_id == fit_id)
        .values(option=option)
    )
    return result.rowcount > 0


def remove_vote(db: Session, user_id: uuid.UUID, fit_id: uuid.UUID) -> None:
    db.execute(delete(FitVote).where(FitVote.user_id == user_id, FitVote.fit_id == fit_id))


def has_votes(db: Session, fit_id: uuid.UUID) -> bool:
    return db.scalar(select(FitVote.fit_id).where(FitVote.fit_id == fit_id).limit(1)) is not None


def vote_counts(db: Session, fit_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict[int, int]]:
    """{fit_id: {option: n}} — options with no votes are left out."""
    rows = db.execute(
        select(FitVote.fit_id, FitVote.option, func.count())
        .where(FitVote.fit_id.in_(fit_ids))
        .group_by(FitVote.fit_id, FitVote.option)
    )
    counts: dict[uuid.UUID, dict[int, int]] = {}
    for fit_id, option, count in rows:
        counts.setdefault(fit_id, {})[option] = count
    return counts


def votes_by_user(
    db: Session, user_id: uuid.UUID, fit_ids: list[uuid.UUID]
) -> dict[uuid.UUID, int]:
    """{fit_id: option} for the fits this user has voted on."""
    rows = db.execute(
        select(FitVote.fit_id, FitVote.option).where(
            FitVote.user_id == user_id, FitVote.fit_id.in_(fit_ids)
        )
    )
    return {fit_id: option for fit_id, option in rows}
