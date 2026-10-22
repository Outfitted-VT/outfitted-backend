from fastapi import APIRouter, HTTPException, status

from app.api.deps import (
    CurrentUser,
    GarmentDetectorDep,
    ProductFinderDep,
    SessionDep,
    StorageDep,
)
from app.garments import DetectionUnavailableError
from app.schemas.detection import DetectionCreate, DetectionRead
from app.schemas.error import ErrorResponse
from app.services.detection import DailyLimitReachedError, detect_pieces
from app.services.image import ImageNotFoundError

router = APIRouter()


@router.post(
    "",
    response_model=DetectionRead,
    summary="Detect the pieces in a photo",
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "model": ErrorResponse,
            "description": "The image doesn't exist or isn't yours.",
            "content": {"application/json": {"example": {"detail": "Image not found"}}},
        },
        status.HTTP_429_TOO_MANY_REQUESTS: {
            "model": ErrorResponse,
            "description": "Daily detection limit reached.",
        },
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "model": ErrorResponse,
            "description": "Detection isn't configured, or the model is unavailable.",
            "content": {
                "application/json": {
                    "example": {"detail": "Piece detection is temporarily unavailable"}
                }
            },
        },
    },
)
def create(
    detection_in: DetectionCreate,
    current_user: CurrentUser,
    db: SessionDep,
    storage: StorageDep,
    detector: GarmentDetectorDep,
    finder: ProductFinderDep,
) -> DetectionRead:
    """
    Suggest the clothing pieces, occasion/style tags, and shop links for one of your photos,
    so you don't have to tag them by hand. Takes a few seconds.

    `items` are in the shape `POST /fits` accepts, with `source: "detected"` and, when the
    model located the piece, a `pin` on this image. Show them as editable suggestions, then send
    the ones the user keeps (and the tags) when posting the fit.

    When shop matching is set up, each located piece also has `matches`: products that look
    like it (Google Lens), best first, and `url` is set to the best one. Let the user pick a
    different match or remove the link before posting.

    Results are stored per image: asking again for the same image returns the same result
    instantly. A photo the model won't process returns empty lists, not an error.
    """
    try:
        return detect_pieces(db, storage, detector, finder, current_user, detection_in.image_id)
    except ImageNotFoundError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Image not found") from None
    except DailyLimitReachedError:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="You've reached today's detection limit. Try again tomorrow.",
        ) from None
    except DetectionUnavailableError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)
        ) from None
