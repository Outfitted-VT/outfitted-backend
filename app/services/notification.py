"""In-app notifications, their settings, and push delivery. Every notification is created through `notify`."""

import uuid
from datetime import datetime, time, timedelta

from sqlalchemy.orm import Session

from app.core.localtime import local_now
from app.core.pagination import decode_cursor, encode_cursor
from app.db.mixins import utcnow
from app.db.session import SessionLocal
from app.models.notification import Notification, NotificationSettings
from app.models.user import User
from app.push import PushMessage, PushResult, PushSender, get_push_sender, push_queue
from app.realtime import hub
from app.repositories import conversation as conversation_repository
from app.repositories import device as device_repository
from app.repositories import notification as repo
from app.repositories import user as user_repository
from app.schemas.notification import NotificationRead, NotificationSettingsRead, NotificationSettingsUpdate
from app.schemas.pagination import Page
from app.schemas.user import UserSummary

GROUPED_TYPES = {"like", "fit_vote", "fit_check_vote", "story_view_milestone"}
GROUP_WINDOW = timedelta(hours=24)
MAX_TRACKED_ACTORS = 100
SHOWN_ACTORS = 2
PREVIEW_LENGTH = 80
INTERNAL_DATA_KEYS = {"actor_ids", "actor_count", "since"}
TYPE_GROUPS = {
    "social": {"follow", "like", "comment", "fit_vote", "fit_check_vote", "circle_added"},
    "messages": {"message"},
    "stories": {"story_reply", "story_view_milestone"},
    "streaks": {"streak_reminder", "streak_milestone", "streak_saved", "streak_lost"},
}
GROUP_OF = {kind: group for group, kinds in TYPE_GROUPS.items() for kind in kinds}
SETTING_FIELDS = ("social", "messages", "stories", "streaks", "quiet_hours_start", "quiet_hours_end")


def _group_key(kind: str, entity_type: str | None, entity_id: uuid.UUID | None) -> str:
    return f"{kind}:{entity_type or ''}:{entity_id or ''}"


def _muted(db: Session, user_id: uuid.UUID, conversation_id: uuid.UUID) -> bool:
    member = conversation_repository.get_member(db, conversation_id, user_id)
    return member is None or member.muted


def _within_window(notification: Notification, now: datetime) -> bool:
    since = datetime.fromisoformat(notification.data["since"])
    return now - since < GROUP_WINDOW


def _merge(notification: Notification, actor: User | None, data: dict, now: datetime) -> bool:
    """Fold another actor (or a newer milestone) into a grouped row. False when nothing changed."""
    merged = dict(notification.data)
    ids = list(merged.get("actor_ids", []))
    if actor is not None:
        if str(actor.id) in ids:
            return False
        ids = [str(actor.id), *ids][:MAX_TRACKED_ACTORS]
        merged["actor_count"] = merged.get("actor_count", 0) + 1
        notification.actor_id = actor.id
    elif all(merged.get(k) == v for k, v in data.items()):
        return False
    merged.update(data, actor_ids=ids)
    notification.data = merged
    notification.created_at = now
    notification.read_at = None
    return True


def _new(
    recipient_id: uuid.UUID, kind: str, actor: User | None, entity_type, entity_id, data: dict, now: datetime
) -> Notification:
    actor_ids = [str(actor.id)] if actor else []
    return Notification(
        user_id=recipient_id,
        actor_id=actor.id if actor else None,
        type=kind,
        entity_type=entity_type,
        entity_id=entity_id,
        data={**data, "actor_ids": actor_ids, "actor_count": len(actor_ids), "since": now.isoformat()},
        group_key=_group_key(kind, entity_type, entity_id),
        created_at=now,
    )


def notify(
    db: Session,
    recipient_id: uuid.UUID,
    kind: str,
    *,
    actor: User | None = None,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    data: dict | None = None,
    conversation_id: uuid.UUID | None = None,
    now: datetime | None = None,
) -> Notification | None:
    """Create (or merge into) a notification, then send it live and by push. Never notifies the actor
    themself, an inactive user, or a member who muted `conversation_id`."""
    if actor is not None and actor.id == recipient_id:
        return None
    recipient = user_repository.get(db, recipient_id)
    if recipient is None or not recipient.is_active:
        return None
    if conversation_id is not None and _muted(db, recipient_id, conversation_id):
        return None
    now = now or utcnow()
    data = data or {}
    existing = None
    if kind in GROUPED_TYPES:
        existing = repo.latest_in_group(db, recipient_id, _group_key(kind, entity_type, entity_id))
    if existing is not None and _within_window(existing, now):
        if not _merge(existing, actor, data, now):
            return None
        notification = existing
    else:
        notification = _new(recipient_id, kind, actor, entity_type, entity_id, data, now)
        repo.add(db, notification)
    db.commit()
    _announce(db, notification)
    return notification


def _announce(db: Session, notification: Notification) -> None:
    [view] = describe(db, [notification])
    hub.publish([notification.user_id], {"type": "notification:new", "notification": view})
    publish_count(db, notification.user_id)
    push_queue.submit(_deliver_in_background, notification.id)


def publish_count(db: Session, user_id: uuid.UUID) -> int:
    unread = repo.unread_count(db, user_id)
    hub.publish([user_id], {"type": "notification:count", "unread": unread})
    return unread


def _name(user: User) -> str:
    return user.full_name or user.username


def _who(actors: list[User], count: int) -> str:
    if not actors:
        return "Someone"
    others = count - 1
    if others <= 0:
        return _name(actors[0])
    return f"{_name(actors[0])} and {others} other{'s' if others > 1 else ''}"


def _quote(text: str | None) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    clipped = text if len(text) <= PREVIEW_LENGTH else text[:PREVIEW_LENGTH] + "…"
    return f"“{clipped}”"


def _plural(word: str, count: int) -> str:
    return word if count <= 1 else f"{word}s"


def _message_text(data: dict, actors: list[User]) -> tuple[str, str]:
    sender = _name(actors[0]) if actors else "Someone"
    preview = data.get("preview") or "Sent a message"
    if data.get("conversation_title"):
        return data["conversation_title"], f"{sender}: {preview}"
    return sender, preview


def render(notification: Notification, actors: list[User]) -> tuple[str, str, str]:
    """(title, body, link) for a notification, with the current names of its actors."""
    data, kind, entity = notification.data, notification.type, notification.entity_id
    count = data.get("actor_count", len(actors))
    who = _who(actors, count)
    conversation = data.get("conversation_id")
    if kind == "follow":
        link = f"/users/{actors[0].username}" if actors else "/notifications"
        return "New follower", f"{who} started following you", link
    if kind == "like":
        return _plural("New like", count), f"{who} liked your fit", f"/fits/{entity}"
    if kind == "comment":
        return "New comment", f"{who} commented: {_quote(data.get('preview'))}", f"/fits/{entity}"
    if kind == "fit_vote":
        return _plural("New vote", count), f"{who} voted on your fit", f"/fits/{entity}"
    if kind == "fit_check_vote":
        return _plural("Fit check vote", count), f"{who} voted on your fit check", f"/conversations/{conversation}?message={entity}"
    if kind == "story_reply":
        return "Story reply", f"{who} replied to your story: {_quote(data.get('preview'))}", f"/conversations/{conversation}"
    if kind == "story_view_milestone":
        return "Story views", f"{data.get('viewers')} people have viewed your story", f"/stories/{entity}/viewers"
    if kind == "circle_added":
        return "New circle", f"{who} added you to {data.get('title') or 'a circle'}", f"/conversations/{entity}"
    if kind == "message":
        title, body = _message_text(data, actors)
        return title, body, f"/conversations/{entity}"
    streak = data.get("count", 0)
    if kind == "streak_reminder":
        hours = data.get("hours_left", 0)
        return f"Keep your {streak}-day streak", f"Post a fit, story, or fit check in the next {hours} hours.", "/streak"
    if kind == "streak_milestone":
        return f"{streak}-day streak!", f"You've shown up {streak} days in a row. Keep it going.", "/streak"
    if kind == "streak_saved":
        left = data.get("freezes_left", 0)
        return "Streak saved", f"A freeze kept your {streak}-day streak alive. {left} left.", "/streak"
    return "Streak ended", f"Your {streak}-day streak ended. Post today to start a new one.", "/streak"


def describe(db: Session, notifications: list[Notification]) -> list[NotificationRead]:
    shown = {n.id: [uuid.UUID(i) for i in n.data.get("actor_ids", [])[:SHOWN_ACTORS]] for n in notifications}
    wanted = list({i for ids in shown.values() for i in ids})
    users = {u.id: u for u in user_repository.get_many(db, wanted)}
    views = []
    for n in notifications:
        actors = [users[i] for i in shown[n.id] if i in users]
        title, body, link = render(n, actors)
        summaries = [UserSummary.model_validate(a) for a in actors]
        public_data = {k: v for k, v in n.data.items() if k not in INTERNAL_DATA_KEYS}
        views.append(
            NotificationRead(
                id=n.id,
                type=n.type,
                actor=summaries[0] if summaries else None,
                actors=summaries,
                actor_count=n.data.get("actor_count", 0),
                entity_type=n.entity_type,
                entity_id=n.entity_id,
                title=title,
                body=body,
                link=link,
                data=public_data,
                read=n.read_at is not None,
                created_at=n.created_at,
            )
        )
    return views


def list_notifications(db: Session, user: User, *, limit: int, cursor: str | None) -> Page[NotificationRead]:
    """Newest first. Raises InvalidCursorError."""
    decoded = decode_cursor(cursor) if cursor else None
    rows = repo.list_newest(db, user.id, limit=limit + 1, cursor=decoded)
    page, more = rows[:limit], len(rows) > limit
    next_cursor = encode_cursor(page[-1].created_at, page[-1].id) if more and page else None
    return Page(items=describe(db, page), next_cursor=next_cursor)


def unread_count(db: Session, user: User) -> int:
    return repo.unread_count(db, user.id)


def mark_read(db: Session, user: User, ids: list[uuid.UUID] | None) -> int:
    """Mark the given notifications read (all of them when ids is None). Returns the unread count."""
    repo.mark_read(db, user.id, ids, utcnow())
    db.commit()
    return publish_count(db, user.id)


def _settings_row(db: Session, user: User) -> NotificationSettings:
    return repo.get_settings(db, user.id) or NotificationSettings(
        user_id=user.id, social=True, messages=True, stories=True, streaks=True
    )


def _settings_view(user: User, row: NotificationSettings) -> NotificationSettingsRead:
    return NotificationSettingsRead(
        **{field: getattr(row, field) for field in SETTING_FIELDS}, timezone=user.timezone
    )


def get_settings(db: Session, user: User) -> NotificationSettingsRead:
    return _settings_view(user, _settings_row(db, user))


def update_settings(db: Session, user: User, changes: NotificationSettingsUpdate) -> NotificationSettingsRead:
    row = _settings_row(db, user)
    for field in changes.model_fields_set:
        value = getattr(changes, field)
        if value is not None or field.startswith("quiet_hours"):
            setattr(row, field, value)
    if row not in db:
        repo.add(db, row)
    db.commit()
    return _settings_view(user, row)


def in_quiet_hours(start: time | None, end: time | None, local: time) -> bool:
    if start is None or end is None or start == end:
        return False
    if start < end:
        return start <= local < end
    return local >= start or local < end


def _push_allowed(row: NotificationSettings, kind: str, timezone: str, now: datetime) -> bool:
    if not getattr(row, GROUP_OF[kind]):
        return False
    local = local_now(now, timezone).time().replace(tzinfo=None)
    return not in_quiet_hours(row.quiet_hours_start, row.quiet_hours_end, local)


def badge_count(db: Session, user_id: uuid.UUID) -> int:
    """Unread notifications plus unread messages, for the iOS app badge."""
    return repo.unread_count(db, user_id) + conversation_repository.total_unread(db, user_id)


def deliver_push(db: Session, notification_id: uuid.UUID, sender: PushSender, now: datetime | None = None) -> int:
    """Push a notification to the recipient's devices if their settings allow it now. Removes tokens the
    provider reports as invalid. Returns how many devices accepted it."""
    notification = repo.get(db, notification_id)
    if notification is None or notification.read_at is not None:
        return 0
    user = user_repository.get(db, notification.user_id)
    devices = device_repository.for_user(db, notification.user_id)
    if not devices or not _push_allowed(_settings_row(db, user), notification.type, user.timezone, now or utcnow()):
        return 0
    [view] = describe(db, [notification])
    badge = badge_count(db, user.id)
    data = {"notification_id": str(notification.id), "type": notification.type, "link": view.link}
    sent = 0
    for device in devices:
        message = PushMessage(
            token=device.token,
            platform=device.platform,
            title=view.title,
            body=view.body,
            data=data,
            badge=badge if device.platform == "ios" else None,
            collapse_key=notification.group_key,
        )
        result = sender.send(message)
        if result is PushResult.INVALID_TOKEN:
            device_repository.remove(db, device.token)
        sent += result is PushResult.SENT
    db.commit()
    return sent


def _deliver_in_background(notification_id: uuid.UUID) -> None:
    with SessionLocal() as db:
        deliver_push(db, notification_id, get_push_sender())
