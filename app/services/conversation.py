"""Messaging rules: conversations, messages, receipts, fit-check votes, and realtime events."""

import uuid
from datetime import timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.pagination import decode_cursor, encode_cursor
from app.core.rate_limit import RateLimiter
from app.db.mixins import utcnow
from app.models.conversation import Conversation, ConversationMember, Message
from app.models.user import User
from app.realtime import hub
from app.repositories import conversation as repo
from app.repositories import image as image_repository
from app.schemas.conversation import (
    CirclePerson,
    ConversationCreate,
    ConversationRead,
    ConversationUpdate,
    MemberRead,
    MessageCreate,
    MessageRead,
    VoteResult,
    VoteTally,
)
from app.schemas.image import ImageRead
from app.schemas.pagination import Page
from app.schemas.user import UserSummary
from app.services.image import get_owned_images

LIVE_FIT_WINDOW = timedelta(hours=24)

send_limiter = RateLimiter(settings.MESSAGE_SEND_LIMIT, settings.MESSAGE_SEND_WINDOW_SECONDS)


class ConversationNotFoundError(Exception):
    """The conversation doesn't exist or the user isn't a member."""


class MessageNotFoundError(Exception):
    pass


class NotInCircleError(Exception):
    pass


class NotSenderError(Exception):
    pass


class NotAFitCheckError(Exception):
    pass


class CannotRenameDirectError(Exception):
    pass


class RateLimitedError(Exception):
    pass


def _membership(db: Session, conversation_id: uuid.UUID, user: User) -> ConversationMember:
    member = repo.get_member(db, conversation_id, user.id)
    if member is None:
        raise ConversationNotFoundError
    return member


def _summary(user: User | None) -> UserSummary | None:
    return UserSummary.model_validate(user) if user is not None else None


def _tally(counts: dict[str, int], my_vote: str | None) -> VoteTally:
    wear, rethink = counts.get("wear", 0), counts.get("rethink", 0)
    total = wear + rethink
    wear_pct = round(wear * 100 / total) if total else 0
    return VoteTally(
        wear=wear,
        rethink=rethink,
        total=total,
        wear_pct=wear_pct,
        rethink_pct=100 - wear_pct if total else 0,
        my_vote=my_vote,
    )


def _image_ids(message: Message) -> list[uuid.UUID]:
    payload = message.payload or {}
    ids = [payload.get("image_id"), (payload.get("product") or {}).get("image_id")]
    return [uuid.UUID(i) for i in ids if i]


def _resolve_payload(message: Message, images: dict[uuid.UUID, ImageRead]) -> dict | None:
    if message.deleted_at is not None or not message.payload:
        return None
    payload = dict(message.payload)
    image_id = payload.pop("image_id", None)
    if image_id:
        payload["image"] = images.get(uuid.UUID(image_id))
    product = payload.get("product")
    if product:
        product = dict(product)
        product_image = product.pop("image_id", None)
        product["image"] = images.get(uuid.UUID(product_image)) if product_image else None
        payload["product"] = product
    return payload


def message_views(db: Session, viewer_id: uuid.UUID | None, messages: list[Message]) -> list[MessageRead]:
    image_ids = [i for m in messages for i in _image_ids(m)]
    images = {i.id: ImageRead.model_validate(i) for i in image_repository.get_many(db, image_ids)} if image_ids else {}
    checks = [m.id for m in messages if m.kind == "fit_check"]
    counts = repo.vote_counts(db, checks)
    mine = repo.votes_by_user(db, viewer_id, checks) if viewer_id else {}
    return [
        MessageRead(
            id=m.id,
            conversation_id=m.conversation_id,
            sender=_summary(m.sender),
            kind=m.kind,
            body=None if m.deleted_at else m.body,
            payload=_resolve_payload(m, images),
            client_id=m.client_id,
            created_at=m.created_at,
            edited_at=m.edited_at,
            deleted_at=m.deleted_at,
            votes=_tally(counts.get(m.id, {}), mine.get(m.id)) if m.kind == "fit_check" else None,
        )
        for m in messages
    ]


def _member_view(member: ConversationMember) -> MemberRead:
    return MemberRead(
        user=UserSummary.model_validate(member.user),
        role=member.role,
        online=hub.is_online(member.user_id),
        last_seen_at=member.user.last_seen_at,
        last_read_at=member.last_read_at,
        last_delivered_at=member.last_delivered_at,
    )


def _conversation_view(
    conversation: Conversation, member: ConversationMember, last: MessageRead | None, unread: int
) -> ConversationRead:
    return ConversationRead(
        id=conversation.id,
        type=conversation.type,
        title=conversation.title,
        created_at=conversation.created_at,
        muted=member.muted,
        unread_count=unread,
        members=[_member_view(m) for m in conversation.members],
        last_message=last,
        last_activity_at=last.created_at if last else conversation.created_at,
    )


def _views(db: Session, user: User, members: list[ConversationMember]) -> list[ConversationRead]:
    ids = [m.conversation_id for m in members]
    lasts = repo.last_messages(db, ids)
    last_views = dict(zip(lasts.keys(), message_views(db, user.id, list(lasts.values()))))
    unread = repo.unread_counts(db, user.id, ids)
    views = [
        _conversation_view(m.conversation, m, last_views.get(m.conversation_id), unread.get(m.conversation_id, 0))
        for m in members
    ]
    return sorted(views, key=lambda v: v.last_activity_at, reverse=True)


def list_conversations(db: Session, user: User) -> list[ConversationRead]:
    return _views(db, user, repo.memberships(db, user.id))


def get_conversation(db: Session, user: User, conversation_id: uuid.UUID) -> ConversationRead:
    return _views(db, user, [_membership(db, conversation_id, user)])[0]


def _direct_key(a: uuid.UUID, b: uuid.UUID) -> str:
    return ":".join(sorted((a.hex, b.hex)))


def _reuse_direct(db: Session, user: User, key: str) -> Conversation | None:
    conversation = repo.get_direct(db, key)
    if conversation is None:
        return None
    member = repo.get_member(db, conversation.id, user.id)
    if member is not None and member.hidden_at is not None:
        member.hidden_at = None
        db.commit()
    return conversation


def create_conversation(db: Session, user: User, data: ConversationCreate) -> tuple[ConversationRead, bool]:
    """Returns the conversation and whether it was newly created. Raises NotInCircleError."""
    others = [i for i in data.member_ids if i != user.id]
    if not others or len(repo.circle_user_ids(db, user.id, others)) != len(others):
        raise NotInCircleError
    key = _direct_key(user.id, others[0]) if data.type == "direct" else None
    if key and (existing := _reuse_direct(db, user, key)):
        return get_conversation(db, user, existing.id), False

    conversation = Conversation(
        type=data.type,
        title=data.title if data.type == "circle" else None,
        created_by=user.id,
        direct_key=key,
    )
    conversation.members = [ConversationMember(user_id=user.id, role="owner")] + [
        ConversationMember(user_id=i, role="member") for i in others
    ]
    try:
        repo.add(db, conversation)
        db.commit()
    except IntegrityError:
        db.rollback()
        if key and (existing := _reuse_direct(db, user, key)):
            return get_conversation(db, user, existing.id), False
        raise
    db.refresh(conversation)
    hub.publish(others, {"type": "conversation:update", "conversation_id": conversation.id})
    return get_conversation(db, user, conversation.id), True


def list_messages(
    db: Session, user: User, conversation_id: uuid.UUID, *, limit: int, before: str | None
) -> Page[MessageRead]:
    """Newest first. Raises ConversationNotFoundError and InvalidCursorError."""
    _membership(db, conversation_id, user)
    cursor = decode_cursor(before) if before else None
    rows = repo.list_messages(db, conversation_id, limit=limit + 1, cursor=cursor)
    page, more = rows[:limit], len(rows) > limit
    next_cursor = encode_cursor(page[-1].created_at, page[-1].id) if more and page else None
    return Page(items=message_views(db, user.id, page), next_cursor=next_cursor)


def _payload(db: Session, user: User, data: MessageCreate) -> dict | None:
    owned = [i for i in (data.image_id, data.product.image_id if data.product else None) if i]
    if owned:
        get_owned_images(db, user, owned)
    if data.kind == "image":
        return {"image_id": str(data.image_id)}
    if data.kind == "fit_check":
        return {
            "image_id": str(data.image_id),
            "question": data.question,
            "context": data.context,
            "fit_id": str(data.fit_id) if data.fit_id else None,
        }
    if data.kind == "product":
        return {"product": data.product.model_dump(mode="json")}
    return None


def send_message(db: Session, user: User, conversation_id: uuid.UUID, data: MessageCreate) -> MessageRead:
    """Raises ConversationNotFoundError, RateLimitedError, and ImageNotFoundError (app.services.image)."""
    member = _membership(db, conversation_id, user)
    if data.client_id and (existing := repo.get_by_client_id(db, user.id, data.client_id)):
        if existing.conversation_id == conversation_id:
            return message_views(db, user.id, [existing])[0]
    if not send_limiter.allow(user.id):
        raise RateLimitedError

    message = Message(
        conversation_id=conversation_id,
        sender_id=user.id,
        kind=data.kind,
        body=data.body if data.kind != "fit_check" else data.question,
        payload=_payload(db, user, data),
        client_id=data.client_id,
    )
    repo.add(db, message)
    repo.unhide_all(db, conversation_id)
    member.last_read_at = member.last_delivered_at = message.created_at
    db.commit()
    db.refresh(message)

    view = message_views(db, None, [message])[0]
    hub.publish(repo.member_ids(db, conversation_id), {"type": "message:new", "message": view})
    return view


def _receipt(member: ConversationMember) -> dict:
    return {
        "type": "receipt:update",
        "conversation_id": member.conversation_id,
        "user_id": member.user_id,
        "last_read_at": member.last_read_at,
        "last_delivered_at": member.last_delivered_at,
    }


def mark_read(db: Session, user: User, conversation_id: uuid.UUID) -> dict:
    member = _membership(db, conversation_id, user)
    member.last_read_at = member.last_delivered_at = utcnow()
    db.commit()
    event = _receipt(member)
    hub.publish(repo.member_ids(db, conversation_id), event)
    return event


def mark_delivered(db: Session, user: User, conversation_id: uuid.UUID) -> dict:
    member = _membership(db, conversation_id, user)
    member.last_delivered_at = utcnow()
    db.commit()
    event = _receipt(member)
    hub.publish(repo.member_ids(db, conversation_id), event)
    return event


def update_conversation(
    db: Session, user: User, conversation_id: uuid.UUID, changes: ConversationUpdate
) -> ConversationRead:
    """Mute is per member; any member can rename a circle. Raises CannotRenameDirectError."""
    member = _membership(db, conversation_id, user)
    fields = changes.model_fields_set
    if "title" in fields:
        if member.conversation.type != "circle":
            raise CannotRenameDirectError
        member.conversation.title = changes.title
    if "muted" in fields and changes.muted is not None:
        member.muted = changes.muted
    db.commit()
    if "title" in fields:
        hub.publish(
            repo.member_ids(db, conversation_id),
            {"type": "conversation:update", "conversation_id": conversation_id},
        )
    return get_conversation(db, user, conversation_id)


def leave_or_hide(db: Session, user: User, conversation_id: uuid.UUID) -> None:
    """Leave a circle, or hide a direct chat until its next message."""
    member = _membership(db, conversation_id, user)
    conversation = member.conversation
    if conversation.type == "direct":
        member.hidden_at = utcnow()
        db.commit()
        return
    conversation.members.remove(member)
    db.flush()
    remaining = repo.member_ids(db, conversation_id)
    if not remaining:
        repo.delete(db, conversation)
    db.commit()
    hub.publish(remaining, {"type": "conversation:update", "conversation_id": conversation_id})


def _member_message(db: Session, user: User, message_id: uuid.UUID) -> Message:
    message = repo.get_message(db, message_id)
    if message is None or repo.get_member(db, message.conversation_id, user.id) is None:
        raise MessageNotFoundError
    return message


def vote(db: Session, user: User, message_id: uuid.UUID, choice: str) -> VoteResult:
    """Raises MessageNotFoundError and NotAFitCheckError."""
    message = _member_message(db, user, message_id)
    if message.kind != "fit_check" or message.deleted_at is not None:
        raise NotAFitCheckError
    try:
        repo.set_vote(db, message.id, user.id, choice)
        db.commit()
    except IntegrityError:
        db.rollback()
        repo.set_vote(db, message.id, user.id, choice)
        db.commit()
    tally = _tally(repo.vote_counts(db, [message.id]).get(message.id, {}), choice)
    result = VoteResult(message_id=message.id, conversation_id=message.conversation_id, **tally.model_dump())
    event = {"type": "vote:update", **result.model_dump(exclude={"my_vote"})}
    hub.publish(repo.member_ids(db, message.conversation_id), event)
    return result


def delete_message(db: Session, user: User, message_id: uuid.UUID) -> None:
    """Soft delete. Raises MessageNotFoundError and NotSenderError."""
    message = _member_message(db, user, message_id)
    if message.sender_id != user.id:
        raise NotSenderError
    if message.deleted_at is None:
        message.deleted_at = utcnow()
        message.body = None
        message.payload = None
        db.commit()
    hub.publish(
        repo.member_ids(db, message.conversation_id),
        {"type": "message:deleted", "conversation_id": message.conversation_id, "message_id": message.id},
    )


def circle(db: Session, user: User, *, limit: int = 30) -> list[CirclePerson]:
    people = repo.circle_users(db, user.id, limit=limit)
    live = repo.users_with_fits_since(db, [p.id for p in people], utcnow() - LIVE_FIT_WINDOW)
    return [
        CirclePerson(
            user=UserSummary.model_validate(p),
            online=hub.is_online(p.id),
            last_seen_at=p.last_seen_at,
            has_live_fit_check=p.id in live,
        )
        for p in people
    ]


def is_member(db: Session, user_id: uuid.UUID, conversation_id: uuid.UUID) -> bool:
    return repo.get_member(db, conversation_id, user_id) is not None


def touch_presence(db: Session, user: User, online: bool) -> None:
    """Record last seen and tell everyone who shares a conversation with the user."""
    user.last_seen_at = utcnow()
    db.commit()
    hub.publish(
        repo.co_member_ids(db, user.id),
        {"type": "presence:update", "user_id": user.id, "online": online, "last_seen_at": user.last_seen_at},
    )


def publish_typing(db: Session, user: User, conversation_id: uuid.UUID, kind: str) -> None:
    others = [i for i in repo.member_ids(db, conversation_id) if i != user.id]
    hub.publish(others, {"type": kind, "conversation_id": conversation_id, "user_id": user.id})

