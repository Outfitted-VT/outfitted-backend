import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response, status

from app.api.deps import CurrentUser, SessionDep
from app.core.pagination import InvalidCursorError
from app.schemas.conversation import (
    CirclePerson,
    ConversationCreate,
    ConversationRead,
    ConversationUpdate,
    MessageCreate,
    MessageRead,
)
from app.schemas.error import ErrorResponse
from app.schemas.pagination import Page
from app.services import conversation as service
from app.services.image import ImageNotFoundError

router = APIRouter()

NOT_FOUND = {
    status.HTTP_404_NOT_FOUND: {
        "model": ErrorResponse,
        "description": "The conversation doesn't exist or you aren't a member.",
        "content": {"application/json": {"example": {"detail": "Conversation not found"}}},
    }
}


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")


@router.get("", response_model=list[ConversationRead], summary="List your conversations")
def list_conversations(current_user: CurrentUser, db: SessionDep) -> list[ConversationRead]:
    """Most recent activity first, with the last message, your unread count, and members' presence."""
    return service.list_conversations(db, current_user)


@router.get("/circle", response_model=list[CirclePerson], summary="Your circle, for starting chats")
def read_circle(current_user: CurrentUser, db: SessionDep) -> list[CirclePerson]:
    """People you follow or who follow you, with online state and whether they posted a fit in the last day."""
    return service.circle(db, current_user)


@router.post(
    "",
    response_model=ConversationRead,
    status_code=status.HTTP_201_CREATED,
    summary="Start a direct chat or a circle",
    responses={
        status.HTTP_200_OK: {"model": ConversationRead, "description": "Existing direct chat reused."},
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "content": {"application/json": {"example": {"detail": "You can only chat with people in your circle"}}},
        },
    },
)
def create_conversation(
    data: ConversationCreate, current_user: CurrentUser, db: SessionDep, response: Response
) -> ConversationRead:
    """A direct chat with someone you already have one with returns that chat (200) instead."""
    try:
        conversation, created = service.create_conversation(db, current_user, data)
    except service.NotInCircleError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="You can only chat with people in your circle"
        ) from None
    if not created:
        response.status_code = status.HTTP_200_OK
    return conversation


@router.get("/{conversation_id}", response_model=ConversationRead, responses=NOT_FOUND, summary="Get a conversation")
def read_conversation(conversation_id: uuid.UUID, current_user: CurrentUser, db: SessionDep) -> ConversationRead:
    try:
        return service.get_conversation(db, current_user, conversation_id)
    except service.ConversationNotFoundError:
        raise _not_found() from None


@router.get(
    "/{conversation_id}/messages",
    response_model=Page[MessageRead],
    responses=NOT_FOUND,
    summary="List messages, newest first",
)
def list_messages(
    conversation_id: uuid.UUID,
    current_user: CurrentUser,
    db: SessionDep,
    before: Annotated[str | None, Query(description="`next_cursor` from the previous page.")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
) -> Page[MessageRead]:
    try:
        return service.list_messages(db, current_user, conversation_id, limit=limit, before=before)
    except service.ConversationNotFoundError:
        raise _not_found() from None
    except InvalidCursorError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid cursor") from None


@router.post(
    "/{conversation_id}/messages",
    response_model=MessageRead,
    status_code=status.HTTP_201_CREATED,
    summary="Send a message",
    responses={
        **NOT_FOUND,
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse, "description": "Image not found or not yours."},
        status.HTTP_429_TOO_MANY_REQUESTS: {"model": ErrorResponse, "description": "Sending too fast."},
    },
)
def send_message(
    conversation_id: uuid.UUID, data: MessageCreate, current_user: CurrentUser, db: SessionDep
) -> MessageRead:
    """
    `kind` is `text` (`body`), `image` (`image_id` from `POST /images`), `fit_check` (`image_id`
    and `question`, optional `context` and `fit_id`), or `product` (`product`). Send a `client_id`
    so retrying a send that already reached the server returns the stored message.
    """
    try:
        return service.send_message(db, current_user, conversation_id, data)
    except service.ConversationNotFoundError:
        raise _not_found() from None
    except ImageNotFoundError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Image not found") from None
    except service.RateLimitedError:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="You're sending messages too fast. Wait a moment.",
        ) from None


@router.post("/{conversation_id}/read", responses=NOT_FOUND, summary="Mark the conversation read")
def mark_read(conversation_id: uuid.UUID, current_user: CurrentUser, db: SessionDep) -> dict:
    try:
        return service.mark_read(db, current_user, conversation_id)
    except service.ConversationNotFoundError:
        raise _not_found() from None


@router.post("/{conversation_id}/delivered", responses=NOT_FOUND, summary="Acknowledge delivery")
def mark_delivered(conversation_id: uuid.UUID, current_user: CurrentUser, db: SessionDep) -> dict:
    try:
        return service.mark_delivered(db, current_user, conversation_id)
    except service.ConversationNotFoundError:
        raise _not_found() from None


@router.patch(
    "/{conversation_id}",
    response_model=ConversationRead,
    responses=NOT_FOUND,
    summary="Mute, or rename a circle",
)
def update_conversation(
    conversation_id: uuid.UUID, changes: ConversationUpdate, current_user: CurrentUser, db: SessionDep
) -> ConversationRead:
    try:
        return service.update_conversation(db, current_user, conversation_id, changes)
    except service.ConversationNotFoundError:
        raise _not_found() from None
    except service.CannotRenameDirectError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Only circles can be renamed"
        ) from None


@router.delete(
    "/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=NOT_FOUND,
    summary="Leave a circle or hide a direct chat",
)
def delete_conversation(conversation_id: uuid.UUID, current_user: CurrentUser, db: SessionDep) -> None:
    try:
        service.leave_or_hide(db, current_user, conversation_id)
    except service.ConversationNotFoundError:
        raise _not_found() from None
