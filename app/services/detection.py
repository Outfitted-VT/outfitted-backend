"""Detecting the clothing pieces in a photo, so people don't have to tag them by hand."""

import uuid
from datetime import UTC, datetime, timedelta

from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.images import to_jpeg
from app.garments import Detection, DetectedPiece, GarmentDetector
from app.models.detection import ImageDetection
from app.models.user import User
from app.repositories import detection as detection_repository
from app.schemas.detection import DetectionRead
from app.schemas.fit import MAX_ITEMS_PER_FIT, MAX_TAGS_PER_KIND, FitItemIn, ItemPin
from app.services.image import get_owned_images
from app.storage import Storage


class DailyLimitReachedError(Exception):
    pass


def _clip(value: str | None, length: int) -> str | None:
    value = " ".join((value or "").split())
    return value[:length] or None


def _pin(piece: DetectedPiece, image_id: uuid.UUID) -> ItemPin | None:
    """The center of the piece's bounding box, as fractions of the image (0-1)."""
    box = piece.box_2d
    if not box or len(box) != 4:
        return None
    ymin, xmin, ymax, xmax = (min(max(v, 0), 1000) / 1000 for v in box)
    if ymax <= ymin or xmax <= xmin:
        return None
    return ItemPin(image_id=image_id, x=round((xmin + xmax) / 2, 4), y=round((ymin + ymax) / 2, 4))


def _to_items(detection: Detection, image_id: uuid.UUID) -> list[FitItemIn]:
    """Turn the model's output into items POST /fits accepts, skipping any that don't fit."""
    items = []
    for piece in detection.items[:MAX_ITEMS_PER_FIT]:
        try:
            items.append(
                FitItemIn(
                    category=piece.category,
                    name=_clip(piece.name, 100) or piece.category,
                    color=_clip(piece.color, 50),
                    pattern=_clip(piece.pattern, 50),
                    material=_clip(piece.material, 50),
                    silhouette=_clip(piece.silhouette, 50),
                    pin=_pin(piece, image_id),
                    source="detected",
                )
            )
        except ValidationError:
            continue
    return items


def _to_tags(tags: list[str]) -> list[str]:
    clean = (_clip(tag, 30) for tag in tags)
    return list(dict.fromkeys(tag.lower() for tag in clean if tag))[:MAX_TAGS_PER_KIND]


def _read(detection: ImageDetection) -> DetectionRead:
    return DetectionRead(image_id=detection.image_id, model=detection.model, **detection.result)


def detect_pieces(
    db: Session, storage: Storage, detector: GarmentDetector, user: User, image_id: uuid.UUID
) -> DetectionRead:
    """Suggest the pieces and tags for one of the user's images. The result is stored, so
    asking again for the same image is free.

    Raises ImageNotFoundError, DailyLimitReachedError, and DetectionUnavailableError.
    """
    [image] = get_owned_images(db, user, [image_id])
    existing = detection_repository.get_for_image(db, image.id)
    if existing is not None:
        return _read(existing)

    since = datetime.now(UTC) - timedelta(days=1)
    if detection_repository.count_since(db, user.id, since) >= settings.DETECTION_DAILY_LIMIT:
        raise DailyLimitReachedError

    detection = detector.detect(to_jpeg(storage.read(image.storage_key)))
    result = {
        "items": [item.model_dump(mode="json") for item in _to_items(detection, image.id)],
        "occasion_tags": _to_tags(detection.occasion_tags),
        "style_tags": _to_tags(detection.style_tags),
    }
    stored = ImageDetection(
        user_id=user.id, image_id=image.id, model=settings.DETECTION_MODEL, result=result
    )
    try:
        detection_repository.add(db, stored)
        db.commit()
    except IntegrityError:
        # The same image was detected by a concurrent request; use that result.
        db.rollback()
        return _read(detection_repository.get_for_image(db, image.id))
    return _read(stored)
