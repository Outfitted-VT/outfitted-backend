import uuid

from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser, SessionDep
from app.schemas.error import ErrorResponse
from app.schemas.sizing import (
    ReferenceGarmentCreate,
    ReferenceGarmentRead,
    SizeTranslateRequest,
    SizeTranslateResponse,
    TrueSizePassportRead,
)
from app.services import sizing as sizing_service

router = APIRouter()

UNAUTHORIZED_RESPONSE = {
    status.HTTP_401_UNAUTHORIZED: {
        "model": ErrorResponse,
        "description": "Missing, invalid, or expired access token.",
        "content": {"application/json": {"example": {"detail": "Not authenticated"}}},
    },
}

GARMENT_NOT_FOUND = {
    status.HTTP_404_NOT_FOUND: {
        "model": ErrorResponse,
        "description": "Reference garment not found in your TrueSize Passport.",
        "content": {"application/json": {"example": {"detail": "Reference garment not found"}}},
    },
}


@router.get(
    "/passport",
    response_model=TrueSizePassportRead,
    summary="Get your TrueSize Passport",
    responses=UNAUTHORIZED_RESPONSE,
)
def read_passport(current_user: CurrentUser, db: SessionDep) -> TrueSizePassportRead:
    """
    Return the user's TrueSize Passport including benchmark reference pieces,
    top anchored brands, and calibrated baseline sizing.
    """
    return sizing_service.get_user_passport(db, current_user)


@router.post(
    "/passport",
    response_model=ReferenceGarmentRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add a benchmark garment to your TrueSize Passport",
    responses=UNAUTHORIZED_RESPONSE,
)
def add_reference(
    data: ReferenceGarmentCreate, current_user: CurrentUser, db: SessionDep
) -> ReferenceGarmentRead:
    """
    Save an owned clothing item (e.g. Levi's 501 30W, Zara M) that fits well
    as an anchor for cross-brand translation.
    """
    return sizing_service.add_reference_garment(db, current_user, data)


@router.delete(
    "/passport/{garment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a benchmark garment from your TrueSize Passport",
    responses={**UNAUTHORIZED_RESPONSE, **GARMENT_NOT_FOUND},
)
def remove_reference(
    garment_id: uuid.UUID, current_user: CurrentUser, db: SessionDep
) -> None:
    """Delete a reference piece from the user's passport."""
    deleted = sizing_service.delete_reference_garment(db, current_user, garment_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reference garment not found")


@router.post(
    "/translate",
    response_model=SizeTranslateResponse,
    summary="Translate size across brands using TrueSize Passport",
    responses=UNAUTHORIZED_RESPONSE,
)
def translate(
    req: SizeTranslateRequest, current_user: CurrentUser, db: SessionDep
) -> SizeTranslateResponse:
    """
    Given a target brand and garment category, calculate the recommended size,
    confidence score, fit notes, and fabric stretch calibration.
    """
    return sizing_service.translate_size(db, current_user, req)
