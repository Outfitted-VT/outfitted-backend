from fastapi import APIRouter, status

from app.api.deps import CurrentUser, SessionDep
from app.schemas.error import ErrorResponse
from app.schemas.impact import ImpactRecordCreate, ImpactRecordRead, UserImpactSummary
from app.services import impact as impact_service

router = APIRouter()

UNAUTHORIZED_RESPONSE = {
    status.HTTP_401_UNAUTHORIZED: {
        "model": ErrorResponse,
        "description": "Missing, invalid, or expired access token.",
        "content": {"application/json": {"example": {"detail": "Not authenticated"}}},
    },
}


@router.get(
    "",
    response_model=UserImpactSummary,
    summary="Get your Returns Saved & Wallet impact metrics",
    responses=UNAUTHORIZED_RESPONSE,
)
def read_impact_summary(current_user: CurrentUser, db: SessionDep) -> UserImpactSummary:
    """
    Get personal return prevention metrics: dollars saved ($32 return overhead + items),
    post-office trips spared, CO2 footprint eliminated, and gamified badge progress.
    """
    return impact_service.get_user_impact_summary(db, current_user)


@router.post(
    "/record",
    response_model=ImpactRecordRead,
    status_code=status.HTTP_201_CREATED,
    summary="Log a return-prevented impact event",
    responses=UNAUTHORIZED_RESPONSE,
)
def create_impact_record(
    data: ImpactRecordCreate, current_user: CurrentUser, db: SessionDep
) -> ImpactRecordRead:
    """
    Log an event where Outfitted (sizing translation, avatar try-on, or friend feedback)
    prevented a wrong-size purchase or return.
    """
    return impact_service.record_impact_event(db, current_user, data)
