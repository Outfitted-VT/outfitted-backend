import uuid

from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser, SessionDep, StorageDep
from app.schemas.error import ErrorResponse
from app.schemas.fit import FitCreate, FitRead, FitUpdate
from app.services import engagement as engagement_service
from app.services.fit import (
    FitNotFoundError,
    ImageAlreadyUsedError,
    InvalidItemPinError,
    NotFitOwnerError,
    create_fit,
    delete_fit,
    describe_fit,
    get_fit,
    update_fit,
)
from app.services.image import ImageNotFoundError

router = APIRouter()


def _error(status_code: int, detail: str, description: str | None = None) -> dict:
    response = {"model": ErrorResponse, "content": {"application/json": {"example": {"detail": detail}}}}
    if description:
        response["description"] = description
    return {status_code: response}


FIT_NOT_FOUND = _error(status.HTTP_404_NOT_FOUND, "Fit not found")
NOT_OWNER = _error(status.HTTP_403_FORBIDDEN, "You can only change your own fits")


@router.post(
    "",
    response_model=FitRead,
    status_code=status.HTTP_201_CREATED,
    summary="Post a fit",
    responses={
        **_error(
            status.HTTP_400_BAD_REQUEST,
            "Image not found",
            "An image id doesn't exist or wasn't uploaded by you.",
        ),
        **_error(
            status.HTTP_409_CONFLICT,
            "Image is already used in another fit",
            "Each uploaded image can be in only one fit.",
        ),
    },
)
def post_fit(data: FitCreate, current_user: CurrentUser, db: SessionDep) -> FitRead:
    """
    Create a fit from images you've uploaded with `POST /images`.

    - **image_ids**: 1-10 images, in display order.
    - **caption**: optional, up to 2200 characters.
    - **items**: up to 30 tagged pieces. `pin` is optional and must reference one of
      this fit's `image_ids`; `x`/`y` are fractions (0-1) of the image's width/height.
    """
    try:
        fit = create_fit(db, current_user, data)
    except ImageNotFoundError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Image not found") from None
    except ImageAlreadyUsedError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Image is already used in another fit"
        ) from None
    return FitRead.from_view(describe_fit(db, current_user, fit))


@router.get("/{fit_id}", response_model=FitRead, summary="Get a fit", responses=FIT_NOT_FOUND)
def read_fit(fit_id: uuid.UUID, current_user: CurrentUser, db: SessionDep) -> FitRead:
    try:
        fit = get_fit(db, fit_id)
    except FitNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fit not found") from None
    return FitRead.from_view(describe_fit(db, current_user, fit))


@router.patch(
    "/{fit_id}",
    response_model=FitRead,
    summary="Edit your fit",
    responses={
        **FIT_NOT_FOUND,
        **NOT_OWNER,
        **_error(
            status.HTTP_400_BAD_REQUEST,
            "Each item pin must reference one of the fit's images",
        ),
    },
)
def edit_fit(
    fit_id: uuid.UUID, changes: FitUpdate, current_user: CurrentUser, db: SessionDep
) -> FitRead:
    """
    Change the caption and/or items. Omitted fields stay the same.
    Sending `items` replaces the whole list. Images can't be changed after posting.
    """
    try:
        fit = update_fit(db, current_user, fit_id, changes)
    except FitNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fit not found") from None
    except NotFitOwnerError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="You can only change your own fits"
        ) from None
    except InvalidItemPinError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Each item pin must reference one of the fit's images",
        ) from None
    return FitRead.from_view(describe_fit(db, current_user, fit))


@router.delete(
    "/{fit_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete your fit",
    responses={**FIT_NOT_FOUND, **NOT_OWNER},
)
def remove_fit(
    fit_id: uuid.UUID, current_user: CurrentUser, db: SessionDep, storage: StorageDep
) -> None:
    """Delete the fit and its photos (except a photo you're also using as your avatar)."""
    try:
        delete_fit(db, storage, current_user, fit_id)
    except FitNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fit not found") from None
    except NotFitOwnerError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="You can only change your own fits"
        ) from None


def _engagement_route(action, fit_id: uuid.UUID, current_user, db) -> None:
    try:
        action(db, current_user, fit_id)
    except FitNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fit not found") from None


@router.put(
    "/{fit_id}/like",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Like a fit",
    responses=FIT_NOT_FOUND,
)
def like(fit_id: uuid.UUID, current_user: CurrentUser, db: SessionDep) -> None:
    """Idempotent: liking a fit you already liked does nothing."""
    _engagement_route(engagement_service.like_fit, fit_id, current_user, db)


@router.delete(
    "/{fit_id}/like",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Unlike a fit",
    responses=FIT_NOT_FOUND,
)
def unlike(fit_id: uuid.UUID, current_user: CurrentUser, db: SessionDep) -> None:
    """Idempotent: unliking a fit you haven't liked does nothing."""
    _engagement_route(engagement_service.unlike_fit, fit_id, current_user, db)


@router.put(
    "/{fit_id}/save",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Save a fit",
    responses=FIT_NOT_FOUND,
)
def save(fit_id: uuid.UUID, current_user: CurrentUser, db: SessionDep) -> None:
    """Bookmark a fit. Saves are private. Idempotent."""
    _engagement_route(engagement_service.save_fit, fit_id, current_user, db)


@router.delete(
    "/{fit_id}/save",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Unsave a fit",
    responses=FIT_NOT_FOUND,
)
def unsave(fit_id: uuid.UUID, current_user: CurrentUser, db: SessionDep) -> None:
    """Idempotent."""
    _engagement_route(engagement_service.unsave_fit, fit_id, current_user, db)
