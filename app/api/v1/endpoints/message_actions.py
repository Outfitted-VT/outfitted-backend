import uuid

from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser, SessionDep
from app.schemas.conversation import VoteIn, VoteResult
from app.schemas.error import ErrorResponse
from app.schemas.fit import SavedPieceRead
from app.schemas.look import SavedLookRead
from app.services import conversation as service
from app.services import styling

router = APIRouter()

NOT_FOUND = {
    status.HTTP_404_NOT_FOUND: {
        "model": ErrorResponse,
        "content": {"application/json": {"example": {"detail": "Message not found"}}},
    }
}


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")


@router.post(
    "/{message_id}/vote",
    response_model=VoteResult,
    summary="Vote on a fit check",
    responses={**NOT_FOUND, status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse}},
)
def vote(message_id: uuid.UUID, data: VoteIn, current_user: CurrentUser, db: SessionDep) -> VoteResult:
    """One vote per member; voting again replaces it. Returns the new percentages."""
    try:
        return service.vote(db, current_user, message_id, data.vote)
    except service.MessageNotFoundError:
        raise _not_found() from None
    except service.NotAFitCheckError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Only fit checks can be voted on"
        ) from None


@router.delete(
    "/{message_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete your message",
    responses={**NOT_FOUND, status.HTTP_403_FORBIDDEN: {"model": ErrorResponse}},
)
def delete_message(message_id: uuid.UUID, current_user: CurrentUser, db: SessionDep) -> None:
    """Soft delete: the message stays in the thread as deleted. Sender only."""
    try:
        service.delete_message(db, current_user, message_id)
    except service.MessageNotFoundError:
        raise _not_found() from None
    except service.NotSenderError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="You can only delete your own messages"
        ) from None


LOOK_NOT_FOUND = {
    status.HTTP_404_NOT_FOUND: {
        "model": ErrorResponse,
        "description": "No styled look (or piece) with that id in a chat you are in.",
        "content": {"application/json": {"example": {"detail": "Look not found"}}},
    }
}


def _look_not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Look not found")


@router.post(
    "/{message_id}/look/save",
    response_model=SavedLookRead,
    status_code=status.HTTP_201_CREATED,
    summary="Save a styled look",
    responses=LOOK_NOT_FOUND,
)
def save_look(message_id: uuid.UUID, current_user: CurrentUser, db: SessionDep) -> SavedLookRead:
    """Saves the whole look (the try-on, the stylist's note and every piece with its link), listed
    with your saved fits: GET /users/me/saved-looks. Saving it again returns your existing save.
    Unsave with DELETE /users/me/saved-looks/{id}."""
    try:
        look = styling.save_look(db, current_user, message_id)
    except styling.LookNotFoundError:
        raise _look_not_found() from None
    return styling.saved_look_views(db, [look])[0]


@router.post(
    "/{message_id}/look/pieces/{index}/save",
    response_model=SavedPieceRead,
    status_code=status.HTTP_201_CREATED,
    summary="Save one piece of a styled look",
    responses=LOOK_NOT_FOUND,
)
def save_look_piece(message_id: uuid.UUID, index: int, current_user: CurrentUser, db: SessionDep) -> SavedPieceRead:
    """`index` is the piece's place in the look, from 0. It goes to your saved pieces. Saving it
    again returns your existing save. Unsave with DELETE /users/me/saved-pieces/{id}."""
    try:
        piece = styling.save_look_piece(db, current_user, message_id, index)
    except styling.LookNotFoundError:
        raise _look_not_found() from None
    return SavedPieceRead.from_model(piece)
