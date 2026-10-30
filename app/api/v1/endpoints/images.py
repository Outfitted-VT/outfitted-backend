import uuid

from fastapi import APIRouter, HTTPException, UploadFile, status

from app.api.deps import CurrentUser, FaceLocatorDep, SessionDep, StorageDep
from app.core.config import settings
from app.core.images import InvalidImageError
from app.faces import FaceLocatorUnavailableError
from app.schemas.error import ErrorResponse
from app.schemas.image import ImageRead
from app.services.image import ImageNotFoundError, NoFaceFoundError, blur_faces, upload_image

router = APIRouter()


@router.post(
    "",
    response_model=ImageRead,
    status_code=status.HTTP_201_CREATED,
    summary="Upload an image",
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "model": ErrorResponse,
            "description": "Not a JPEG, PNG, or WebP image, or the file is corrupt.",
        },
        status.HTTP_413_CONTENT_TOO_LARGE: {
            "model": ErrorResponse,
            "description": "File is larger than 10 MB.",
        },
    },
)
def create_image(
    file: UploadFile, current_user: CurrentUser, db: SessionDep, storage: StorageDep
) -> ImageRead:
    """
    Upload one image as `multipart/form-data` with the field name `file`.

    Returns an image `id` to attach to a fit (`POST /fits`) or set as your avatar
    (`PATCH /users/me`). Accepts JPEG, PNG, or WebP up to 10 MB. Images are converted
    to WebP, scaled to at most 2048px, and stripped of metadata such as GPS location.
    """
    data = file.file.read(settings.MAX_UPLOAD_BYTES + 1)
    if len(data) > settings.MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="Image must be 10 MB or smaller"
        )
    try:
        image = upload_image(db, storage, current_user, data)
    except InvalidImageError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from None
    return ImageRead.model_validate(image)


@router.post(
    "/{image_id}/blur-faces",
    response_model=ImageRead,
    status_code=status.HTTP_201_CREATED,
    summary="Blur the faces in one of your images",
    responses={
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "The image doesn't exist or isn't yours.",
            "content": {"application/json": {"example": {"detail": "Image not found"}}},
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "model": ErrorResponse,
            "description": "No face was found to blur.",
            "content": {"application/json": {"example": {"detail": "No face found in this photo"}}},
        },
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "model": ErrorResponse,
            "description": "Face blurring isn't configured, or the model is unavailable.",
        },
    },
)
def create_blurred_image(
    image_id: uuid.UUID,
    current_user: CurrentUser,
    db: SessionDep,
    storage: StorageDep,
    locator: FaceLocatorDep,
) -> ImageRead:
    """
    Make a copy of one of your images with every face blurred, e.g. a try-on result you want
    to post without showing your face. Takes a few seconds.

    Returns the new image; post it with `POST /fits` instead of the original. The original is
    unchanged, and the copy keeps its `generated` flag. If no face is found you get `422`, so
    never assume the face is hidden without a `201`.
    """
    try:
        image = blur_faces(db, storage, locator, current_user, image_id)
    except ImageNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found") from None
    except NoFaceFoundError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="No face found in this photo"
        ) from None
    except FaceLocatorUnavailableError as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from None
    return ImageRead.model_validate(image)
