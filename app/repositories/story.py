"""Database access for stories and story views. Queries only; never commits."""

import uuid
from datetime import datetime

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.orm import Session

from app.core.pagination import Cursor
from app.models.story import Story, StoryView
from app.models.user import User
from app.repositories.user import circle_ids, mutual_ids


def add(db: Session, instance) -> None:
    db.add(instance)
    db.flush()


def _active(now: datetime):
    return and_(Story.deleted_at.is_(None), Story.expires_at > now, User.is_active.is_(True))


def visible_to(viewer_id: uuid.UUID):
    """Stories the viewer may see: their own, public ones, and close-friends ones from mutual follows."""
    return or_(
        Story.user_id == viewer_id,
        Story.visibility == "public",
        Story.user_id.in_(mutual_ids(viewer_id)),
    )


def get_visible(db: Session, story_id: uuid.UUID, viewer_id: uuid.UUID, now: datetime) -> Story | None:
    return db.scalar(
        select(Story).join(Story.author).where(Story.id == story_id, _active(now), visible_to(viewer_id))
    )


def active_count(db: Session, user_id: uuid.UUID, now: datetime) -> int:
    return db.scalar(
        select(func.count()).select_from(Story).join(Story.author).where(Story.user_id == user_id, _active(now))
    )


def list_visible(db: Session, viewer_id: uuid.UUID, author_ids, now: datetime) -> list[Story]:
    """Active stories by the given authors that the viewer may see, oldest first."""
    return list(
        db.scalars(
            select(Story)
            .join(Story.author)
            .where(Story.user_id.in_(author_ids), _active(now), visible_to(viewer_id))
            .order_by(Story.created_at, Story.id)
        )
    )


def feed_author_ids(viewer_id: uuid.UUID):
    """Subquery of the viewer and everyone in their circle."""
    return select(User.id).where(or_(User.id == viewer_id, User.id.in_(circle_ids(viewer_id))))


def audience_ids(db: Session, story: Story) -> list[uuid.UUID]:
    """Everyone whose story feed shows this story, except the author."""
    source = mutual_ids(story.user_id) if story.visibility == "close_friends" else circle_ids(story.user_id)
    return list(db.scalars(source))


def viewed_ids(db: Session, viewer_id: uuid.UUID, story_ids: list[uuid.UUID]) -> set[uuid.UUID]:
    if not story_ids:
        return set()
    return set(
        db.scalars(
            select(StoryView.story_id).where(StoryView.viewer_id == viewer_id, StoryView.story_id.in_(story_ids))
        )
    )


def view_counts(db: Session, story_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not story_ids:
        return {}
    rows = db.execute(
        select(StoryView.story_id, func.count()).where(StoryView.story_id.in_(story_ids)).group_by(StoryView.story_id)
    )
    return {story_id: count for story_id, count in rows}


def add_view(db: Session, story_id: uuid.UUID, viewer_id: uuid.UUID) -> None:
    """Raises IntegrityError if the viewer already viewed the story."""
    db.add(StoryView(story_id=story_id, viewer_id=viewer_id))
    db.flush()


def has_viewed(db: Session, story_id: uuid.UUID, viewer_id: uuid.UUID) -> bool:
    return db.get(StoryView, (story_id, viewer_id)) is not None


def list_viewers(db: Session, story_id: uuid.UUID, *, limit: int, cursor: Cursor | None) -> list[StoryView]:
    """Newest first. The cursor is the (viewed_at, viewer_id) of the last row."""
    statement = select(StoryView).where(StoryView.story_id == story_id)
    if cursor is not None:
        statement = statement.where(
            or_(
                StoryView.viewed_at < cursor.created_at,
                and_(StoryView.viewed_at == cursor.created_at, StoryView.viewer_id < cursor.id),
            )
        )
    statement = statement.order_by(StoryView.viewed_at.desc(), StoryView.viewer_id.desc()).limit(limit)
    return list(db.scalars(statement))


def users_with_stories(db: Session, viewer_id: uuid.UUID, user_ids: list[uuid.UUID], now: datetime) -> dict[uuid.UUID, bool]:
    """{user_id: has_unseen} for the given users who have an active story the viewer may see."""
    if not user_ids:
        return {}
    seen = select(StoryView.story_id).where(StoryView.viewer_id == viewer_id)
    rows = db.execute(
        select(Story.user_id, Story.id.in_(seen))
        .join(Story.author)
        .where(Story.user_id.in_(user_ids), _active(now), visible_to(viewer_id))
    )
    flags: dict[uuid.UUID, bool] = {}
    for user_id, was_seen in rows:
        flags[user_id] = flags.get(user_id, False) or not was_seen
    return flags


def expired_before(db: Session, cutoff: datetime) -> list[Story]:
    return list(db.scalars(select(Story).where(Story.expires_at < cutoff)))


def delete_many(db: Session, story_ids: list[uuid.UUID]) -> None:
    db.execute(delete(StoryView).where(StoryView.story_id.in_(story_ids)))
    db.execute(delete(Story).where(Story.id.in_(story_ids)))


def image_ids_in_use(db: Session, image_ids: list[uuid.UUID]) -> set[uuid.UUID]:
    if not image_ids:
        return set()
    return set(db.scalars(select(Story.image_id).where(Story.image_id.in_(image_ids))))
