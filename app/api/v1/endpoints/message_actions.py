import uuid

from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser, SessionDep
from app.schemas.conversation import VoteIn, VoteResult
from app.schemas.error import ErrorResponse
from app.services import conversation as service

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
