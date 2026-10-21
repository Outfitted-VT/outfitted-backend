from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser, SessionDep, StorageDep, TryOnGeneratorDep
from app.schemas.error import ErrorResponse
from app.schemas.tryon import TryOnCreate, TryOnRead
from app.services.image import ImageNotFoundError
from app.services.tryon import DailyLimitReachedError, create_tryon
from app.tryon import TryOnBlockedError, TryOnUnavailableError

router = APIRouter()


@router.post(
    "",
    response_model=TryOnRead,
    status_code=status.HTTP_201_CREATED,
    summary="Generate a virtual try-on",
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "model": ErrorResponse,
            "description": "An image doesn't exist or isn't yours.",
            "content": {"application/json": {"example": {"detail": "Image not found"}}},
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "model": ErrorResponse,
            "description": "The model refused these photos (safety filters) or returned no image.",
            "content": {
                "application/json": {
                    "example": {"detail": "We couldn't create a try-on from these photos"}
                }
            },
        },
        status.HTTP_429_TOO_MANY_REQUESTS: {
            "model": ErrorResponse,
            "description": "Daily try-on limit reached.",
            "content": {
                "application/json": {
                    "example": {"detail": "You've reached today's try-on limit. Try again tomorrow."}
                }
            },
        },
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "model": ErrorResponse,
            "description": "Try-on isn't configured, or the model is unavailable. Retry later.",
            "content": {
                "application/json": {"example": {"detail": "Try-on is temporarily unavailable"}}
            },
        },
    },
)
def create(
    tryon_in: TryOnCreate,
    current_user: CurrentUser,
    db: SessionDep,
    storage: StorageDep,
    generator: TryOnGeneratorDep,
) -> TryOnRead:
    """
    Put the outfit from one photo onto a photo of yourself.

    1. Upload both photos with `POST /images`: a photo of yourself (`person_image_id`) and a
       photo of the outfit (`outfit_image_id`), either on its own or worn by someone.
    2. Call this endpoint. Generation takes several seconds, often 10–30.
    3. To post it, create a fit with `result_image.id` in `image_ids` (`POST /fits`).

    The result is a new image you own, with `generated: true` so clients can label it as
    AI-generated. Each user can make a limited number of try-ons per day.
    """
    try:
        tryon = create_tryon(
            db, storage, generator, current_user, tryon_in.person_image_id, tryon_in.outfit_image_id
        )
    except ImageNotFoundError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Image not found") from None
    except DailyLimitReachedError:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="You've reached today's try-on limit. Try again tomorrow.",
        ) from None
    except TryOnBlockedError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
        ) from None
    except TryOnUnavailableError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)
        ) from None
    return TryOnRead.model_validate(tryon)
