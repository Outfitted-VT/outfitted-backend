"""Fit Stories: 24-hour photos shared with your circle, their views, replies, and cleanup."""

import uuid
from datetime import datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.pagination import decode_cursor, encode_cursor
from app.db.mixins import utcnow
from app.models.story import Story
from app.models.user import User
from app.realtime import hub
from app.repositories import fit as fit_repository
from app.repositories import image as image_repository
from app.repositories import story as repo
from app.repositories import user as user_repository
from app.schemas.conversation import MessageRead
from app.schemas.image import ImageRead
from app.schemas.pagination import Page
from app.schemas.story import StoryCreate, StoryGroup, StoryRead, StoryReplyCreate, StoryViewerRead
from app.schemas.user import UserSummary
from app.services import conversation as conversation_service
from app.services import notification as notifications
from app.services import streak as streaks
from app.services.image import get_owned_images
from app.storage import Storage

STORY_LIFETIME = timedelta(hours=24)
CLEANUP_AFTER = timedelta(days=7)
MAX_ACTIVE_STORIES = 20
VIEW_MILESTONES = (10, 50, 100)


class StoryNotFoundError(Exception):
    """The story doesn't exist, expired, was deleted, or the viewer may not see it."""


class NotStoryOwnerError(Exception):
    pass


class StoryLimitError(Exception):
    pass


class StoryFitNotFoundError(Exception):
    """fit_id isn't one of the author's fits, or it's in their vault."""


class OwnStoryReplyError(Exception):
    pass


class UserNotFoundError(Exception):
    pass


def _story_views(db: Session, viewer: User, stories: list[Story]) -> list[StoryRead]:
    ids = [s.id for s in stories]
    seen = repo.viewed_ids(db, viewer.id, ids)
    own = [s.id for s in stories if s.user_id == viewer.id]
    counts = repo.view_counts(db, own)
    return [
        StoryRead(
            id=s.id,
            user_id=s.user_id,
            image=ImageRead.model_validate(s.image),
            caption=s.caption,
            fit_id=s.fit_id,
            visibility=s.visibility,
            created_at=s.created_at,
            expires_at=s.expires_at,
            seen=s.user_id == viewer.id or s.id in seen,
            view_count=counts.get(s.id, 0) if s.user_id == viewer.id else None,
        )
        for s in stories
    ]


def _group(user: User, views: list[StoryRead]) -> StoryGroup:
    return StoryGroup(
        user=UserSummary.model_validate(user),
        stories=views,
        has_unseen=any(not view.seen for view in views),
        latest_at=views[-1].created_at if views else None,
    )


def _groups(db: Session, viewer: User, stories: list[Story]) -> list[StoryGroup]:
    authors: dict[uuid.UUID, User] = {}
    by_user: dict[uuid.UUID, list[StoryRead]] = {}
    for story, view in zip(stories, _story_views(db, viewer, stories)):
        authors[story.user_id] = story.author
        by_user.setdefault(story.user_id, []).append(view)
    return [_group(authors[user_id], views) for user_id, views in by_user.items()]


def _feed_order(viewer: User):
    return lambda group: (group.user.id != viewer.id, not group.has_unseen, -group.latest_at.timestamp())


def _visible_story(db: Session, viewer: User, story_id: uuid.UUID) -> Story:
    story = repo.get_visible(db, story_id, viewer.id, utcnow())
    if story is None:
        raise StoryNotFoundError
    return story


def _own_story(db: Session, owner: User, story_id: uuid.UUID) -> Story:
    story = _visible_story(db, owner, story_id)
    if story.user_id != owner.id:
        raise NotStoryOwnerError
    return story


def _check_fit(db: Session, author: User, fit_id: uuid.UUID | None) -> None:
    if fit_id is None:
        return
    fit = fit_repository.get(db, fit_id)
    if fit is None or fit.user_id != author.id or fit.privacy_tier == "vault":
        raise StoryFitNotFoundError


def create_story(db: Session, author: User, data: StoryCreate) -> StoryRead:
    """Raises ImageNotFoundError (app.services.image), StoryFitNotFoundError, and StoryLimitError."""
    [image] = get_owned_images(db, author, [data.image_id])
    _check_fit(db, author, data.fit_id)
    now = utcnow()
    if repo.active_count(db, author.id, now) >= MAX_ACTIVE_STORIES:
        raise StoryLimitError
    story = Story(
        user_id=author.id,
        image=image,
        caption=data.caption,
        fit_id=data.fit_id,
        visibility=data.visibility,
        created_at=now,
        expires_at=now + STORY_LIFETIME,
    )
    repo.add(db, story)
    db.commit()
    event = {"type": "story:new", "story_id": story.id, "user": UserSummary.model_validate(author)}
    hub.publish(repo.audience_ids(db, story), event)
    streaks.record_activity(db, author)
    return _story_views(db, author, [story])[0]


def feed(db: Session, viewer: User) -> list[StoryGroup]:
    """Your circle's active stories grouped by person: yours first, then unseen, then most recent."""
    stories = repo.list_visible(db, viewer.id, repo.feed_author_ids(viewer.id), utcnow())
    return sorted(_groups(db, viewer, stories), key=_feed_order(viewer))


def user_stories(db: Session, viewer: User, user_id: uuid.UUID) -> StoryGroup:
    """The user's active stories the viewer may see (possibly none). Raises UserNotFoundError."""
    user = user_repository.get(db, user_id)
    if user is None or not user.is_active:
        raise UserNotFoundError
    stories = repo.list_visible(db, viewer.id, [user_id], utcnow())
    return _group(user, _story_views(db, viewer, stories))


def view_story(db: Session, viewer: User, story_id: uuid.UUID) -> None:
    """Idempotent. Your own views aren't recorded. Raises StoryNotFoundError."""
    story = _visible_story(db, viewer, story_id)
    if story.user_id == viewer.id or repo.has_viewed(db, story.id, viewer.id):
        return
    try:
        repo.add_view(db, story.id, viewer.id)
        db.commit()
    except IntegrityError:
        db.rollback()
        return
    view_count = repo.view_counts(db, [story.id]).get(story.id, 0)
    hub.publish(
        [story.user_id],
        {
            "type": "story:viewed",
            "story_id": story.id,
            "viewer": UserSummary.model_validate(viewer),
            "view_count": view_count,
        },
    )
    if view_count in VIEW_MILESTONES:
        notifications.notify(
            db, story.user_id, "story_view_milestone", entity_type="story", entity_id=story.id,
            data={"viewers": view_count},
        )


def list_viewers(
    db: Session, owner: User, story_id: uuid.UUID, *, limit: int, cursor: str | None
) -> Page[StoryViewerRead]:
    """Newest first. Raises StoryNotFoundError, NotStoryOwnerError, and InvalidCursorError."""
    story = _own_story(db, owner, story_id)
    decoded = decode_cursor(cursor) if cursor else None
    rows = repo.list_viewers(db, story.id, limit=limit + 1, cursor=decoded)
    page, more = rows[:limit], len(rows) > limit
    next_cursor = encode_cursor(page[-1].viewed_at, page[-1].viewer_id) if more and page else None
    return Page(
        items=[StoryViewerRead(user=UserSummary.model_validate(v.viewer), viewed_at=v.viewed_at) for v in page],
        next_cursor=next_cursor,
    )


def delete_story(db: Session, owner: User, story_id: uuid.UUID) -> None:
    """Soft delete. Raises StoryNotFoundError and NotStoryOwnerError."""
    story = _own_story(db, owner, story_id)
    story.deleted_at = utcnow()
    db.commit()


def reply(db: Session, viewer: User, story_id: uuid.UUID, data: StoryReplyCreate) -> MessageRead:
    """Send a story_reply message to the owner's direct chat. Raises StoryNotFoundError, OwnStoryReplyError,
    and the errors of conversation_service.send_story_reply."""
    story = _visible_story(db, viewer, story_id)
    if story.user_id == viewer.id:
        raise OwnStoryReplyError
    payload = {"story_id": str(story.id), "image_id": str(story.image_id), "caption": story.caption}
    message, created = conversation_service.send_story_reply(
        db, viewer, story.user_id, payload, data.body, data.client_id
    )
    if not created:
        return message
    notifications.notify(
        db, story.user_id, "story_reply", actor=viewer, entity_type="story", entity_id=story.id,
        data={"preview": data.body, "conversation_id": str(message.conversation_id), "message_id": str(message.id)},
        conversation_id=message.conversation_id,
    )
    return message


def cleanup_expired(db: Session, storage: Storage, now: datetime | None = None) -> int:
    """Hard-delete stories that expired over 7 days ago, and their images when nothing else uses them.
    Returns how many stories were removed."""
    stories = repo.expired_before(db, (now or utcnow()) - CLEANUP_AFTER)
    if not stories:
        return 0
    images = {s.image_id: s.image for s in stories if s.image is not None}
    repo.delete_many(db, [s.id for s in stories])
    orphans = [i for i in image_repository.get_many(db, list(images)) if not image_repository.is_in_use(db, i)]
    keys = [i.storage_key for i in orphans]
    for image in orphans:
        image_repository.delete(db, image)
    db.commit()
    for key in keys:
        storage.delete(key)
    return len(stories)
