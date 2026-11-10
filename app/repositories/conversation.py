"""Database access for conversations, messages, and fit-check votes. Queries only; never commits."""

import uuid
from datetime import datetime

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.orm import Session

from app.core.pagination import Cursor
from app.models.conversation import Conversation, ConversationMember, FitCheckVote, Message
from app.models.fit import Fit
from app.models.user import User
from app.repositories.user import circle_ids


def get(db: Session, conversation_id: uuid.UUID) -> Conversation | None:
    return db.get(Conversation, conversation_id)


def get_member(db: Session, conversation_id: uuid.UUID, user_id: uuid.UUID) -> ConversationMember | None:
    return db.get(ConversationMember, (conversation_id, user_id))


def get_direct(db: Session, direct_key: str) -> Conversation | None:
    return db.scalar(select(Conversation).where(Conversation.direct_key == direct_key))


def add(db: Session, instance) -> None:
    db.add(instance)
    db.flush()


def delete(db: Session, instance) -> None:
    db.delete(instance)
    db.flush()


def memberships(db: Session, user_id: uuid.UUID) -> list[ConversationMember]:
    """The user's visible conversations (not hidden)."""
    return list(
        db.scalars(
            select(ConversationMember).where(
                ConversationMember.user_id == user_id, ConversationMember.hidden_at.is_(None)
            )
        )
    )


def member_ids(db: Session, conversation_id: uuid.UUID) -> list[uuid.UUID]:
    return list(
        db.scalars(
            select(ConversationMember.user_id).where(
                ConversationMember.conversation_id == conversation_id
            )
        )
    )


def co_member_ids(db: Session, user_id: uuid.UUID) -> set[uuid.UUID]:
    """Everyone who shares at least one conversation with the user."""
    mine = select(ConversationMember.conversation_id).where(ConversationMember.user_id == user_id)
    return set(
        db.scalars(
            select(ConversationMember.user_id).where(
                ConversationMember.conversation_id.in_(mine), ConversationMember.user_id != user_id
            )
        )
    )


def unhide_all(db: Session, conversation_id: uuid.UUID) -> None:
    db.execute(
        update(ConversationMember)
        .where(ConversationMember.conversation_id == conversation_id)
        .values(hidden_at=None)
    )


def last_messages(db: Session, conversation_ids: list[uuid.UUID]) -> dict[uuid.UUID, Message]:
    if not conversation_ids:
        return {}
    newest = (
        select(Message.conversation_id, func.max(Message.created_at).label("created_at"))
        .where(Message.conversation_id.in_(conversation_ids))
        .group_by(Message.conversation_id)
        .subquery()
    )
    rows = db.scalars(
        select(Message).join(
            newest,
            and_(
                Message.conversation_id == newest.c.conversation_id,
                Message.created_at == newest.c.created_at,
            ),
        )
    )
    return {message.conversation_id: message for message in rows}


def unread_counts(db: Session, user_id: uuid.UUID, conversation_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not conversation_ids:
        return {}
    rows = db.execute(
        select(Message.conversation_id, func.count())
        .join(
            ConversationMember,
            and_(
                ConversationMember.conversation_id == Message.conversation_id,
                ConversationMember.user_id == user_id,
            ),
        )
        .where(
            Message.conversation_id.in_(conversation_ids),
            Message.sender_id != user_id,
            Message.deleted_at.is_(None),
            or_(
                ConversationMember.last_read_at.is_(None),
                Message.created_at > ConversationMember.last_read_at,
            ),
        )
        .group_by(Message.conversation_id)
    )
    return {conversation_id: count for conversation_id, count in rows}


def list_messages(
    db: Session, conversation_id: uuid.UUID, *, limit: int, cursor: Cursor | None
) -> list[Message]:
    """Newest first; with a cursor, only messages strictly older than it."""
    statement = select(Message).where(Message.conversation_id == conversation_id)
    if cursor is not None:
        statement = statement.where(
            or_(
                Message.created_at < cursor.created_at,
                and_(Message.created_at == cursor.created_at, Message.id < cursor.id),
            )
        )
    statement = statement.order_by(Message.created_at.desc(), Message.id.desc()).limit(limit)
    return list(db.scalars(statement))


def get_message(db: Session, message_id: uuid.UUID) -> Message | None:
    return db.get(Message, message_id)


def get_by_client_id(db: Session, sender_id: uuid.UUID, client_id: str) -> Message | None:
    return db.scalar(
        select(Message).where(Message.sender_id == sender_id, Message.client_id == client_id)
    )


def set_vote(db: Session, message_id: uuid.UUID, user_id: uuid.UUID, vote: str) -> bool:
    """True for the member's first vote on the message."""
    existing = db.get(FitCheckVote, (message_id, user_id))
    if existing is None:
        db.add(FitCheckVote(message_id=message_id, user_id=user_id, vote=vote))
    else:
        existing.vote = vote
    db.flush()
    return existing is None


def vote_counts(db: Session, message_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict[str, int]]:
    if not message_ids:
        return {}
    rows = db.execute(
        select(FitCheckVote.message_id, FitCheckVote.vote, func.count())
        .where(FitCheckVote.message_id.in_(message_ids))
        .group_by(FitCheckVote.message_id, FitCheckVote.vote)
    )
    counts: dict[uuid.UUID, dict[str, int]] = {}
    for message_id, vote, count in rows:
        counts.setdefault(message_id, {})[vote] = count
    return counts


def votes_by_user(db: Session, user_id: uuid.UUID, message_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not message_ids:
        return {}
    rows = db.execute(
        select(FitCheckVote.message_id, FitCheckVote.vote).where(
            FitCheckVote.user_id == user_id, FitCheckVote.message_id.in_(message_ids)
        )
    )
    return {message_id: vote for message_id, vote in rows}


def circle_user_ids(db: Session, user_id: uuid.UUID, candidate_ids: list[uuid.UUID]) -> set[uuid.UUID]:
    """The candidates who are active and in the user's circle."""
    return set(
        db.scalars(
            select(User.id).where(
                User.id.in_(candidate_ids), User.is_active.is_(True), User.id.in_(circle_ids(user_id))
            )
        )
    )


def circle_users(db: Session, user_id: uuid.UUID, *, limit: int) -> list[User]:
    return list(
        db.scalars(
            select(User)
            .where(User.is_active.is_(True), User.id.in_(circle_ids(user_id)))
            .order_by(User.last_seen_at.desc().nulls_last(), User.username)
            .limit(limit)
        )
    )


def users_with_fits_since(db: Session, user_ids: list[uuid.UUID], since: datetime) -> set[uuid.UUID]:
    if not user_ids:
        return set()
    return set(
        db.scalars(
            select(Fit.user_id).where(
                Fit.user_id.in_(user_ids), Fit.created_at >= since, Fit.privacy_tier != "vault"
            )
        )
    )


def total_unread(db: Session, user_id: uuid.UUID) -> int:
    """Unread messages across the user's visible conversations."""
    ids = [m.conversation_id for m in memberships(db, user_id)]
    return sum(unread_counts(db, user_id, ids).values())
