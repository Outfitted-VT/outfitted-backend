import uuid
from datetime import datetime, timezone

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.orm import Session

from app.models.message import DirectMessage
from app.models.user import User


def send_message(
    db: Session,
    sender_id: uuid.UUID,
    recipient_id: uuid.UUID,
    content: str,
    fit_id: uuid.UUID | None = None,
) -> DirectMessage:
    msg = DirectMessage(
        sender_id=sender_id,
        recipient_id=recipient_id,
        content=content,
        fit_id=fit_id,
    )
    db.add(msg)
    db.flush()
    return msg


def list_messages_between(
    db: Session,
    user_a_id: uuid.UUID,
    user_b_id: uuid.UUID,
    limit: int = 50,
) -> list[DirectMessage]:
    return list(
        db.scalars(
            select(DirectMessage)
            .where(
                or_(
                    and_(DirectMessage.sender_id == user_a_id, DirectMessage.recipient_id == user_b_id),
                    and_(DirectMessage.sender_id == user_b_id, DirectMessage.recipient_id == user_a_id),
                )
            )
            .order_by(DirectMessage.created_at.asc(), DirectMessage.id.asc())
            .limit(limit)
        )
    )


def mark_as_read(db: Session, recipient_id: uuid.UUID, sender_id: uuid.UUID) -> int:
    now = datetime.now(timezone.utc)
    result = db.execute(
        update(DirectMessage)
        .where(
            DirectMessage.recipient_id == recipient_id,
            DirectMessage.sender_id == sender_id,
            DirectMessage.read_at.is_(None),
        )
        .values(read_at=now)
    )
    db.flush()
    return result.rowcount


def list_threads(db: Session, user_id: uuid.UUID) -> list[dict]:
    """Find all distinct conversation partners for user_id with their last message and unread count."""
    # Find all partner user IDs
    sent_to = select(DirectMessage.recipient_id.label("partner_id")).where(DirectMessage.sender_id == user_id)
    received_from = select(DirectMessage.sender_id.label("partner_id")).where(DirectMessage.recipient_id == user_id)
    partner_ids_query = sent_to.union(received_from)
    partner_ids = list(db.scalars(partner_ids_query))

    threads = []
    for partner_id in partner_ids:
        partner = db.get(User, partner_id)
        if not partner or not partner.is_active:
            continue

        # Get last message between user_id and partner_id
        last_msg = db.scalars(
            select(DirectMessage)
            .where(
                or_(
                    and_(DirectMessage.sender_id == user_id, DirectMessage.recipient_id == partner_id),
                    and_(DirectMessage.sender_id == partner_id, DirectMessage.recipient_id == user_id),
                )
            )
            .order_by(DirectMessage.created_at.desc(), DirectMessage.id.desc())
            .limit(1)
        ).first()

        # Unread messages sent by partner to user_id
        unread = db.scalar(
            select(func.count(DirectMessage.id)).where(
                DirectMessage.sender_id == partner_id,
                DirectMessage.recipient_id == user_id,
                DirectMessage.read_at.is_(None),
            )
        ) or 0

        if last_msg:
            threads.append({
                "partner": partner,
                "last_message": last_msg,
                "unread_count": unread,
            })

    # Sort threads by last message created_at descending
    threads.sort(key=lambda t: t["last_message"].created_at, reverse=True)
    return threads
