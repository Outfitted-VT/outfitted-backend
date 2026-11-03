from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser, SessionDep
from app.models.fit import Fit
from app.repositories import message as message_repository
from app.repositories import user as user_repository
from app.schemas.error import ErrorResponse
from app.schemas.message import MessageCreate, MessageRead, MessageThreadRead

router = APIRouter()

USER_NOT_FOUND = {
    status.HTTP_404_NOT_FOUND: {
        "model": ErrorResponse,
        "description": "User not found or inactive.",
        "content": {"application/json": {"example": {"detail": "User not found"}}},
    }
}


@router.get(
    "/threads",
    response_model=list[MessageThreadRead],
    summary="List your conversation threads",
)
def list_threads(current_user: CurrentUser, db: SessionDep) -> list[MessageThreadRead]:
    """Return all conversations ordered by most recent message, with partner info and unread counts."""
    threads = message_repository.list_threads(db, current_user.id)
    return [
        MessageThreadRead(
            partner=t["partner"],
            last_message=MessageRead.from_model(t["last_message"]),
            unread_count=t["unread_count"],
        )
        for t in threads
    ]


@router.get(
    "/{username}",
    response_model=list[MessageRead],
    summary="Get message history with a user",
    responses=USER_NOT_FOUND,
)
def get_conversation(
    username: str,
    current_user: CurrentUser,
    db: SessionDep,
) -> list[MessageRead]:
    """Retrieve chronological messages between you and the specified user."""
    partner = user_repository.get_by_username(db, username)
    if not partner or not partner.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    messages = message_repository.list_messages_between(db, current_user.id, partner.id)
    # Automatically mark incoming messages as read
    message_repository.mark_as_read(db, current_user.id, partner.id)
    db.commit()
    return [MessageRead.from_model(m) for m in messages]


@router.post(
    "/{username}",
    response_model=MessageRead,
    status_code=status.HTTP_201_CREATED,
    summary="Send a direct message (optionally attaching a fit)",
    responses=USER_NOT_FOUND,
)
def send_message(
    username: str,
    data: MessageCreate,
    current_user: CurrentUser,
    db: SessionDep,
) -> MessageRead:
    partner = user_repository.get_by_username(db, username)
    if not partner or not partner.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if data.fit_id is not None:
        fit = db.get(Fit, data.fit_id)
        if not fit:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Attached fit not found")

    message = message_repository.send_message(
        db,
        sender_id=current_user.id,
        recipient_id=partner.id,
        content=data.content,
        fit_id=data.fit_id,
    )
    db.commit()
    return MessageRead.from_model(message)


@router.post(
    "/{username}/read",
    summary="Mark messages from user as read",
    responses=USER_NOT_FOUND,
)
def mark_read(
    username: str,
    current_user: CurrentUser,
    db: SessionDep,
) -> dict[str, bool]:
    partner = user_repository.get_by_username(db, username)
    if not partner or not partner.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    message_repository.mark_as_read(db, current_user.id, partner.id)
    db.commit()
    return {"ok": True}
