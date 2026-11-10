from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser, PageCursor, PageLimit, SessionDep
from app.core.pagination import InvalidCursorError
from app.schemas.error import ErrorResponse
from app.schemas.notification import MarkRead, NotificationRead, UnreadCount
from app.schemas.pagination import Page
from app.services import notification as service

router = APIRouter()


@router.get(
    "",
    response_model=Page[NotificationRead],
    summary="Your notifications, newest first",
    responses={status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse}},
)
def list_notifications(
    current_user: CurrentUser, db: SessionDep, limit: PageLimit = 20, cursor: PageCursor = None
) -> Page[NotificationRead]:
    """Each has display-ready `title` and `body`, and a `link` to open."""
    try:
        return service.list_notifications(db, current_user, limit=limit, cursor=cursor)
    except InvalidCursorError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid cursor") from None


@router.get("/unread-count", response_model=UnreadCount, summary="How many are unread")
def unread_count(current_user: CurrentUser, db: SessionDep) -> UnreadCount:
    return UnreadCount(unread=service.unread_count(db, current_user))


@router.post("/read", response_model=UnreadCount, summary="Mark notifications read")
def mark_read(data: MarkRead, current_user: CurrentUser, db: SessionDep) -> UnreadCount:
    """Send `{"ids": [...]}` or `{"all": true}`. Returns the new unread count."""
    return UnreadCount(unread=service.mark_read(db, current_user, None if data.all else data.ids))
