from fastapi import APIRouter, HTTPException, UploadFile, status

from app.api.deps import CurrentUser, SessionDep, StorageDep
from app.core.config import settings
from app.core.images import InvalidImageError
from app.schemas.error import ErrorResponse
from app.schemas.image import ImageRead
from app.services.image import upload_image

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
