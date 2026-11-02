import uuid

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.api.deps import CurrentUser, SessionDep
from app.db.mixins import utcnow
from app.models.memory import OutfitMemory
from app.models.wardrobe import WardrobeItem
from app.schemas.error import ErrorResponse
from app.schemas.memory import OutfitMemoryCreate, OutfitMemoryRead

router = APIRouter()

UNAUTHORIZED_RESPONSE = {
    status.HTTP_401_UNAUTHORIZED: {
        "model": ErrorResponse,
        "description": "Missing, invalid, or expired access token.",
    },
}

MEMORY_NOT_FOUND = {
    status.HTTP_404_NOT_FOUND: {
        "model": ErrorResponse,
        "description": "Outfit memory not found.",
    },
}


@router.get(
    "",
    response_model=list[OutfitMemoryRead],
    summary="List your daily outfit memories for the calendar",
    responses=UNAUTHORIZED_RESPONSE,
)
def list_outfit_memories(
    current_user: CurrentUser,
    db: SessionDep,
    year: int | None = Query(None, ge=2000, le=2100, description="Filter by year (e.g. 2026)"),
    month: int | None = Query(None, ge=1, le=12, description="Filter by month (1-12)"),
) -> list[OutfitMemory]:
    stmt = select(OutfitMemory).where(OutfitMemory.user_id == current_user.id)
    if year is not None and month is not None:
        prefix = f"{year:04d}-{month:02d}"
        stmt = stmt.where(OutfitMemory.date.startswith(prefix))
    elif year is not None:
        prefix = f"{year:04d}-"
        stmt = stmt.where(OutfitMemory.date.startswith(prefix))

    stmt = stmt.order_by(OutfitMemory.date.desc(), OutfitMemory.created_at.desc())
    return list(db.scalars(stmt).all())


@router.post(
    "",
    response_model=OutfitMemoryRead,
    status_code=status.HTTP_201_CREATED,
    summary="Log a daily outfit memory",
    responses=UNAUTHORIZED_RESPONSE,
)
def create_outfit_memory(
    current_user: CurrentUser,
    db: SessionDep,
    payload: OutfitMemoryCreate,
) -> OutfitMemory:
    memory = OutfitMemory(
        user_id=current_user.id,
        date=payload.date,
        title=payload.title,
        photo_url=payload.photo_url,
        notes=payload.notes,
        weather=payload.weather,
        rating=payload.rating,
    )
    memory.tagged_pieces = payload.tagged_pieces
    db.add(memory)

    # If auto_log_wear is enabled and tagged pieces are present, increment wear counts
    if payload.auto_log_wear and payload.tagged_pieces:
        for piece_name in payload.tagged_pieces:
            stripped = piece_name.strip().lower()
            if not stripped:
                continue
            matching_item = db.scalar(
                select(WardrobeItem).where(
                    WardrobeItem.user_id == current_user.id,
                    WardrobeItem.name.ilike(f"%{piece_name.strip()}%"),
                )
            )
            if matching_item:
                matching_item.times_worn += 1
                matching_item.last_worn_at = utcnow()

    db.commit()
    db.refresh(memory)
    return memory


@router.get(
    "/{memory_id}",
    response_model=OutfitMemoryRead,
    summary="Get an outfit memory",
    responses={**UNAUTHORIZED_RESPONSE, **MEMORY_NOT_FOUND},
)
def get_outfit_memory(
    memory_id: uuid.UUID,
    current_user: CurrentUser,
    db: SessionDep,
) -> OutfitMemory:
    memory = db.scalar(
        select(OutfitMemory).where(
            OutfitMemory.id == memory_id,
            OutfitMemory.user_id == current_user.id,
        )
    )
    if not memory:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Outfit memory not found")
    return memory


@router.delete(
    "/{memory_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an outfit memory",
    responses={**UNAUTHORIZED_RESPONSE, **MEMORY_NOT_FOUND},
)
def delete_outfit_memory(
    memory_id: uuid.UUID,
    current_user: CurrentUser,
    db: SessionDep,
) -> None:
    memory = db.scalar(
        select(OutfitMemory).where(
            OutfitMemory.id == memory_id,
            OutfitMemory.user_id == current_user.id,
        )
    )
    if not memory:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Outfit memory not found")

    db.delete(memory)
    db.commit()
