import uuid

from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser, PageCursor, PageLimit, SessionDep
from app.core.pagination import InvalidCursorError
from app.schemas.conversation import MessageRead
from app.schemas.error import ErrorResponse
from app.schemas.pagination import Page
from app.schemas.story import StoryCreate, StoryGroup, StoryRead, StoryReplyCreate, StoryViewerRead
from app.services import conversation as conversation_service
from app.services import story as service
from app.services.image import ImageNotFoundError

router = APIRouter()


def _error(code: int, detail: str) -> dict:
    return {code: {"model": ErrorResponse, "content": {"application/json": {"example": {"detail": detail}}}}}


NOT_FOUND = _error(status.HTTP_404_NOT_FOUND, "Story not found")
NOT_OWNER = _error(status.HTTP_403_FORBIDDEN, "Only the story's owner can do that")


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Story not found")


def _not_owner() -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the story's owner can do that")


@router.post(
    "",
    response_model=StoryRead,
    status_code=status.HTTP_201_CREATED,
    summary="Post a story",
    responses={
        **_error(status.HTTP_400_BAD_REQUEST, "Image not found"),
        **_error(status.HTTP_409_CONFLICT, "You can have at most 20 active stories"),
    },
)
def create_story(data: StoryCreate, current_user: CurrentUser, db: SessionDep) -> StoryRead:
    """Visible for 24 hours. `close_friends` stories are shown only to people you follow who follow you back."""
    try:
        return service.create_story(db, current_user, data)
    except ImageNotFoundError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Image not found") from None
    except service.StoryFitNotFoundError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Fit not found") from None
    except service.StoryLimitError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"You can have at most {service.MAX_ACTIVE_STORIES} active stories",
        ) from None


@router.get("/feed", response_model=list[StoryGroup], summary="Stories from your circle")
def story_feed(current_user: CurrentUser, db: SessionDep) -> list[StoryGroup]:
    """Grouped by person: your own first, then people with unseen stories, then most recent."""
    return service.feed(db, current_user)


@router.post(
    "/{story_id}/view", status_code=status.HTTP_204_NO_CONTENT, responses=NOT_FOUND, summary="Mark a story seen"
)
def view_story(story_id: uuid.UUID, current_user: CurrentUser, db: SessionDep) -> None:
    """Idempotent. Viewing your own story isn't counted."""
    try:
        service.view_story(db, current_user, story_id)
    except service.StoryNotFoundError:
        raise _not_found() from None


@router.get(
    "/{story_id}/viewers",
    response_model=Page[StoryViewerRead],
    responses={**NOT_FOUND, **NOT_OWNER, **_error(status.HTTP_400_BAD_REQUEST, "Invalid cursor")},
    summary="Who viewed your story",
)
def story_viewers(
    story_id: uuid.UUID, current_user: CurrentUser, db: SessionDep, limit: PageLimit = 20, cursor: PageCursor = None
) -> Page[StoryViewerRead]:
    """Owner only. Most recent viewers first."""
    try:
        return service.list_viewers(db, current_user, story_id, limit=limit, cursor=cursor)
    except service.StoryNotFoundError:
        raise _not_found() from None
    except service.NotStoryOwnerError:
        raise _not_owner() from None
    except InvalidCursorError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid cursor") from None


@router.delete(
    "/{story_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={**NOT_FOUND, **NOT_OWNER},
    summary="Delete your story",
)
def delete_story(story_id: uuid.UUID, current_user: CurrentUser, db: SessionDep) -> None:
    try:
        service.delete_story(db, current_user, story_id)
    except service.StoryNotFoundError:
        raise _not_found() from None
    except service.NotStoryOwnerError:
        raise _not_owner() from None


@router.post(
    "/{story_id}/reply",
    response_model=MessageRead,
    status_code=status.HTTP_201_CREATED,
    responses={
        **NOT_FOUND,
        **_error(status.HTTP_400_BAD_REQUEST, "You can't reply to your own story"),
        **_error(status.HTTP_403_FORBIDDEN, "You can only chat with people in your circle"),
        **_error(status.HTTP_429_TOO_MANY_REQUESTS, "You're sending messages too fast. Wait a moment."),
    },
    summary="Reply to a story in a direct chat",
)
def reply_to_story(
    story_id: uuid.UUID, data: StoryReplyCreate, current_user: CurrentUser, db: SessionDep
) -> MessageRead:
    """Sends a `story_reply` message to the owner, starting a direct chat if you don't have one."""
    try:
        return service.reply(db, current_user, story_id, data)
    except service.StoryNotFoundError:
        raise _not_found() from None
    except service.OwnStoryReplyError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You can't reply to your own story") from None
    except conversation_service.NotInCircleError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="You can only chat with people in your circle"
        ) from None
    except conversation_service.RateLimitedError:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="You're sending messages too fast. Wait a moment.",
        ) from None
    except conversation_service.ClientIdConflictError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="client_id was already used in another conversation"
        ) from None
