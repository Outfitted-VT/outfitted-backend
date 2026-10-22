"""Detecting the clothing pieces in a photo, so people don't have to tag them by hand."""

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.images import crop_jpeg, to_jpeg
from app.garments import Detection, DetectedPiece, GarmentDetector
from app.models.detection import ImageDetection
from app.models.user import User
from app.repositories import detection as detection_repository
from app.schemas.detection import DetectedItem, DetectionRead
from app.schemas.fit import MAX_ITEMS_PER_FIT, MAX_TAGS_PER_KIND, ItemPin
from app.services.image import get_owned_images
from app.shopping import ProductFinder
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


def _to_items(detection: Detection, image_id: uuid.UUID) -> list[tuple[DetectedPiece, DetectedItem]]:
    """Turn the model's output into items POST /fits accepts, skipping any that don't fit.
    Each comes with the piece it came from, for its bounding box."""
    items = []
    for piece in detection.items[:MAX_ITEMS_PER_FIT]:
        try:
            item = DetectedItem(
                category=piece.category,
                name=_clip(piece.name, 100) or piece.category,
                color=_clip(piece.color, 50),
                pattern=_clip(piece.pattern, 50),
                material=_clip(piece.material, 50),
                silhouette=_clip(piece.silhouette, 50),
                pin=_pin(piece, image_id),
                source="detected",
            )
        except ValidationError:
            continue
        items.append((piece, item))
    return items


def _with_matches(
    jpeg: bytes, items: list[tuple[DetectedPiece, DetectedItem]], finder: ProductFinder
) -> list[DetectedItem]:
    """Look up products that look like each located piece, in parallel, and use the best one
    as the item's shop link. Pieces without a box, or beyond the per-photo cap, get none."""
    searchable = [
        (i, piece) for i, (piece, item) in enumerate(items) if item.pin is not None
    ][: settings.SHOP_MATCH_MAX_ITEMS]
    if not searchable:
        return [item for _, item in items]

    def find(index: int, piece: DetectedPiece):
        item = items[index][1]
        description = " ".join(filter(None, [item.color, item.pattern, item.material, item.name]))
        return finder.find(crop_jpeg(jpeg, piece.box_2d), description)

    with ThreadPoolExecutor(max_workers=min(4, len(searchable))) as pool:
        found = dict(zip((i for i, _ in searchable), pool.map(find, *zip(*searchable))))

    result = []
    for i, (_, item) in enumerate(items):
        matches = found.get(i) or []
        for match in matches:
            try:
                # Validates the link as the item's URL; skip matches with links it rejects.
                item = DetectedItem.model_validate(
                    {**item.model_dump(), "url": match.link, "matches": matches}
                )
                break
            except ValidationError:
                continue
        result.append(item)
    return result


def _to_tags(tags: list[str]) -> list[str]:
    clean = (_clip(tag, 30) for tag in tags)
    return list(dict.fromkeys(tag.lower() for tag in clean if tag))[:MAX_TAGS_PER_KIND]


def _read(detection: ImageDetection) -> DetectionRead:
    return DetectionRead(image_id=detection.image_id, model=detection.model, **detection.result)


def detect_pieces(
    db: Session,
    storage: Storage,
    detector: GarmentDetector,
    finder: ProductFinder,
    user: User,
    image_id: uuid.UUID,
) -> DetectionRead:
    """Suggest the pieces, tags, and shop links for one of the user's images. The result is
    stored, so asking again for the same image is free.

    Raises ImageNotFoundError, DailyLimitReachedError, and DetectionUnavailableError.
    """
    [image] = get_owned_images(db, user, [image_id])
    existing = detection_repository.get_for_image(db, image.id)
    if existing is not None:
        return _read(existing)

    since = datetime.now(UTC) - timedelta(days=1)
    if detection_repository.count_since(db, user.id, since) >= settings.DETECTION_DAILY_LIMIT:
        raise DailyLimitReachedError

    jpeg = to_jpeg(storage.read(image.storage_key))
    detection = detector.detect(jpeg)
    items = _with_matches(jpeg, _to_items(detection, image.id), finder)
    result = {
        "items": [item.model_dump(mode="json") for item in items],
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
