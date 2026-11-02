import uuid

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.api.deps import CurrentUser, SessionDep
from app.db.mixins import utcnow
from app.models.wardrobe import WardrobeItem
from app.schemas.error import ErrorResponse
from app.schemas.wardrobe import (
    PrimaryCategory,
    WardrobeItemCreate,
    WardrobeItemRead,
    WardrobeItemUpdate,
    WardrobeSummaryRead,
)

router = APIRouter()

UNAUTHORIZED_RESPONSE = {
    status.HTTP_401_UNAUTHORIZED: {
        "model": ErrorResponse,
        "description": "Missing, invalid, or expired access token.",
    },
}

ITEM_NOT_FOUND = {
    status.HTTP_404_NOT_FOUND: {
        "model": ErrorResponse,
        "description": "Wardrobe item not found.",
    },
}


@router.get(
    "",
    response_model=list[WardrobeItemRead],
    summary="List your digital wardrobe items",
    responses=UNAUTHORIZED_RESPONSE,
)
def list_wardrobe_items(
    current_user: CurrentUser,
    db: SessionDep,
    category: PrimaryCategory | None = Query(None, description="Filter by shoes, clothing, or accessories"),
) -> list[WardrobeItem]:
    stmt = select(WardrobeItem).where(WardrobeItem.user_id == current_user.id)
    if category:
        stmt = stmt.where(WardrobeItem.primary_category == category)
    stmt = stmt.order_by(WardrobeItem.created_at.desc())
    return list(db.scalars(stmt).all())


@router.get(
    "/summary",
    response_model=WardrobeSummaryRead,
    summary="Get wardrobe valuation and cost-per-wear analytics",
    responses=UNAUTHORIZED_RESPONSE,
)
def get_wardrobe_summary(current_user: CurrentUser, db: SessionDep) -> WardrobeSummaryRead:
    items = list(
        db.scalars(select(WardrobeItem).where(WardrobeItem.user_id == current_user.id)).all()
    )
    total_pieces = len(items)
    total_val = sum(it.price for it in items)
    total_wears = sum(it.times_worn for it in items)
    avg_cpw = round(total_val / total_wears, 2) if total_wears > 0 else round(total_val, 2)

    shoes_cnt = sum(1 for it in items if it.primary_category == "shoes")
    clothing_cnt = sum(1 for it in items if it.primary_category == "clothing")
    accessories_cnt = sum(1 for it in items if it.primary_category == "accessories")

    return WardrobeSummaryRead(
        total_pieces=total_pieces,
        total_valuation=round(total_val, 2),
        average_cost_per_wear=avg_cpw,
        shoes_count=shoes_cnt,
        clothing_count=clothing_cnt,
        accessories_count=accessories_cnt,
    )


@router.post(
    "",
    response_model=WardrobeItemRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add an item to your wardrobe",
    responses=UNAUTHORIZED_RESPONSE,
)
def create_wardrobe_item(
    current_user: CurrentUser,
    db: SessionDep,
    payload: WardrobeItemCreate,
) -> WardrobeItem:
    item = WardrobeItem(
        user_id=current_user.id,
        primary_category=payload.primary_category,
        sub_category=payload.sub_category,
        name=payload.name,
        brand=payload.brand,
        color=payload.color,
        price=payload.price,
        times_worn=payload.times_worn,
        tag=payload.tag,
        image_url=payload.image_url,
        notes=payload.notes,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.get(
    "/{item_id}",
    response_model=WardrobeItemRead,
    summary="Get a wardrobe item",
    responses={**UNAUTHORIZED_RESPONSE, **ITEM_NOT_FOUND},
)
def get_wardrobe_item(
    item_id: uuid.UUID,
    current_user: CurrentUser,
    db: SessionDep,
) -> WardrobeItem:
    item = db.scalar(
        select(WardrobeItem).where(
            WardrobeItem.id == item_id,
            WardrobeItem.user_id == current_user.id,
        )
    )
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Wardrobe item not found")
    return item


@router.patch(
    "/{item_id}",
    response_model=WardrobeItemRead,
    summary="Update a wardrobe item",
    responses={**UNAUTHORIZED_RESPONSE, **ITEM_NOT_FOUND},
)
def update_wardrobe_item(
    item_id: uuid.UUID,
    payload: WardrobeItemUpdate,
    current_user: CurrentUser,
    db: SessionDep,
) -> WardrobeItem:
    item = db.scalar(
        select(WardrobeItem).where(
            WardrobeItem.id == item_id,
            WardrobeItem.user_id == current_user.id,
        )
    )
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Wardrobe item not found")

    update_data = payload.model_dump(exclude_unset=True)
    for field, val in update_data.items():
        setattr(item, field, val)

    db.commit()
    db.refresh(item)
    return item


@router.post(
    "/{item_id}/wear",
    response_model=WardrobeItemRead,
    summary="Log a wear for a wardrobe item",
    responses={**UNAUTHORIZED_RESPONSE, **ITEM_NOT_FOUND},
)
def log_item_wear(
    item_id: uuid.UUID,
    current_user: CurrentUser,
    db: SessionDep,
) -> WardrobeItem:
    """Increment times_worn and update last_worn_at, recalculating cost-per-wear."""
    item = db.scalar(
        select(WardrobeItem).where(
            WardrobeItem.id == item_id,
            WardrobeItem.user_id == current_user.id,
        )
    )
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Wardrobe item not found")

    item.times_worn += 1
    item.last_worn_at = utcnow()
    db.commit()
    db.refresh(item)
    return item


@router.delete(
    "/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a wardrobe item",
    responses={**UNAUTHORIZED_RESPONSE, **ITEM_NOT_FOUND},
)
def delete_wardrobe_item(
    item_id: uuid.UUID,
    current_user: CurrentUser,
    db: SessionDep,
) -> None:
    item = db.scalar(
        select(WardrobeItem).where(
            WardrobeItem.id == item_id,
            WardrobeItem.user_id == current_user.id,
        )
    )
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Wardrobe item not found")

    db.delete(item)
    db.commit()
