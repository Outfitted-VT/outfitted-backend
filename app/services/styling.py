"""Style a Friend: someone asks a chat to style them, and a friend sends a look back.

Both are chat messages:

- `style_request` ("style me"): an optional note (`body`) and an optional photo of the asker
  (`image_id`). Whoever answers may use that photo for a try-on of the look.
- `styled_look`: answers one request (`request_id`) with pieces taken from the stylist's saved
  pieces, saved fits or new uploads, each with its own link, and optionally a try-on of the look
  on the asker's photo. The pieces are copied into the message, so the look stays as sent even
  if the stylist unsaves or the poster edits a fit later.

The person who gets the look can save one piece (to their saved pieces) or the whole look (a
SavedLook, listed with their saved fits).
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.conversation import Message
from app.core.pagination import decode_cursor, encode_cursor
from app.models.engagement import FitSave, SavedLook, SavedPiece
from app.models.fit import Fit, FitImage, FitItem
from app.models.image import Image
from app.models.tryon import TryOn
from app.models.user import User
from app.repositories import conversation as conversation_repository
from app.repositories import engagement as engagement_repository
from app.repositories import fit as fit_repository
from app.repositories import image as image_repository
from app.schemas.conversation import LookIn, LookPieceIn
from app.schemas.image import ImageRead
from app.schemas.look import LookPieceRead, SavedLookRead
from app.schemas.user import UserSummary
from app.services.engagement import photo_for
from app.services.fit import FitNotFoundError, get_fit
from app.services.image import ImageNotFoundError, get_owned_images


class StyleRequestNotFoundError(Exception):
    """No style request with that id in this chat (or it was deleted)."""


class OwnStyleRequestError(Exception):
    """You can't answer your own style request."""


class LookPieceNotFoundError(Exception):
    """A piece's saved piece, fit or fit item doesn't exist or isn't yours to use."""


class LookTryOnNotFoundError(Exception):
    """The try-on isn't yours, or has no result photo."""


class LookNotFoundError(Exception):
    """No styled look (or piece) with that id that the user can see."""


class SavedLookNotFoundError(Exception):
    """No saved look with that id (or it's someone else's)."""


# --- Asking --------------------------------------------------------------------------------


def request_payload(db: Session, user: User, image_id: uuid.UUID | None) -> dict:
    """The photo must be the asker's own. Raises ImageNotFoundError."""
    if image_id is not None:
        get_owned_images(db, user, [image_id])
    return {"image_id": str(image_id) if image_id else None}


def answerable_request(db: Session, user: User, conversation_id: uuid.UUID, request_id: uuid.UUID) -> Message:
    """A live style request in this chat from someone else. Raises StyleRequestNotFoundError and
    OwnStyleRequestError."""
    request = conversation_repository.get_message(db, request_id)
    if (
        request is None
        or request.conversation_id != conversation_id
        or request.kind != "style_request"
        or request.deleted_at is not None
    ):
        raise StyleRequestNotFoundError
    if request.sender_id == user.id:
        raise OwnStyleRequestError
    return request


# --- Styling -------------------------------------------------------------------------------


def _from_saved_piece(db: Session, user: User, piece_id: uuid.UUID) -> dict:
    saved = engagement_repository.get_saved_piece(db, user.id, piece_id)
    if saved is None:
        raise LookPieceNotFoundError
    return {
        "category": saved.category,
        "name": saved.name,
        "brand": saved.brand,
        "color": saved.color,
        "url": saved.url,
        "image_id": str(saved.image_id) if saved.image_id else None,
        "pin": {"x": saved.pin_x, "y": saved.pin_y} if saved.pin_x is not None else None,
        "zoom": saved.zoom,
        "fit_id": str(saved.fit_id) if saved.fit_id else None,
        "source_username": saved.source_username,
    }


def _from_fit_item(db: Session, user: User, fit_id: uuid.UUID, item_id: uuid.UUID) -> dict:
    try:
        fit = get_fit(db, fit_id, user)
    except FitNotFoundError:
        raise LookPieceNotFoundError from None
    index, item = next(((i, it) for i, it in enumerate(fit.items) if it.id == item_id), (None, None))
    if item is None:
        raise LookPieceNotFoundError
    image, zoom = photo_for(fit, item, index)
    return {
        "category": item.category,
        "name": item.name,
        "brand": item.brand,
        "color": item.color,
        "url": item.url,
        "image_id": str(image.id) if image else None,
        "pin": {"x": item.pin_x, "y": item.pin_y} if zoom else None,
        "zoom": zoom,
        "fit_id": str(fit.id),
        "source_username": fit.author.username,
    }


def _from_upload(db: Session, user: User, piece: LookPieceIn) -> dict:
    get_owned_images(db, user, [piece.image_id])
    return {
        "category": piece.category,
        "name": piece.name,
        "brand": None,
        "color": None,
        "url": None,
        "image_id": str(piece.image_id),
        "pin": None,
        "zoom": False,
        "fit_id": None,
        "source_username": None,
    }


def _look_piece(db: Session, user: User, piece: LookPieceIn) -> dict:
    if piece.saved_piece_id is not None:
        result = _from_saved_piece(db, user, piece.saved_piece_id)
    elif piece.fit_id is not None:
        result = _from_fit_item(db, user, piece.fit_id, piece.item_id)
    else:
        result = _from_upload(db, user, piece)
    # The stylist's own name, brand, color, link or category win over the source's.
    for field in ("category", "name", "brand", "color", "url"):
        value = getattr(piece, field)
        if value is not None:
            result[field] = value
    return result


def look_payload(
    db: Session, user: User, conversation_id: uuid.UUID, request_id: uuid.UUID, look: LookIn
) -> dict:
    """Raises StyleRequestNotFoundError, OwnStyleRequestError, LookPieceNotFoundError,
    LookTryOnNotFoundError, and ImageNotFoundError (an uploaded piece that isn't the user's)."""
    request = answerable_request(db, user, conversation_id, request_id)
    pieces = [_look_piece(db, user, piece) for piece in look.pieces]
    tryon_image_id = None
    if look.tryon_id is not None:
        tryon = db.get(TryOn, look.tryon_id)
        if tryon is None or tryon.user_id != user.id or tryon.result_image_id is None:
            raise LookTryOnNotFoundError
        tryon_image_id = str(tryon.result_image_id)
    return {"request_id": str(request.id), "tryon_image_id": tryon_image_id, "pieces": pieces}


def look_image_ids(payload: dict) -> list[str]:
    """Every photo a styled look shows: the try-on and each piece's photo."""
    ids = [payload.get("tryon_image_id")] + [p.get("image_id") for p in payload.get("pieces", [])]
    return [i for i in ids if i]


# --- Try-on of a look on the asker's photo ---------------------------------------------------


def _saved_clothing_ids(db: Session, user: User, image_ids: list[uuid.UUID]) -> set[uuid.UUID]:
    """Which of these photos the stylist may dress the friend in besides their own uploads: photos
    of their saved pieces and of fits they saved, unless the poster turned try-ons off."""
    if not image_ids:
        return set()
    allowed: set[uuid.UUID] = set()
    pieces = db.scalars(
        select(SavedPiece).where(SavedPiece.user_id == user.id, SavedPiece.image_id.in_(image_ids))
    ).all()
    for piece in pieces:
        fit = fit_repository.get(db, piece.fit_id) if piece.fit_id else None
        if fit is None or fit.user_id == user.id or fit.allow_friend_try_on:
            allowed.add(piece.image_id)
    saved_fit = (
        select(Fit.id)
        .join(FitSave, FitSave.fit_id == Fit.id)
        .where(FitSave.user_id == user.id)
        .where((Fit.allow_friend_try_on.is_(True)) | (Fit.user_id == user.id))
        .where(fit_repository.visible_to(user.id))
    )
    allowed.update(
        db.scalars(select(FitImage.image_id).where(FitImage.fit_id.in_(saved_fit), FitImage.image_id.in_(image_ids)))
    )
    allowed.update(
        db.scalars(select(FitItem.image_id).where(FitItem.fit_id.in_(saved_fit), FitItem.image_id.in_(image_ids)))
    )
    return allowed


def tryon_access(
    db: Session, user: User, request_id: uuid.UUID, person_image_id: uuid.UUID, clothing_ids: list[uuid.UUID]
) -> tuple[Image, set[uuid.UUID]]:
    """For a try-on that styles a friend: the asker's photo from their request, and the clothing
    photos the stylist may use besides their own. Raises StyleRequestNotFoundError,
    OwnStyleRequestError, and ImageNotFoundError (not the request's photo)."""
    request = conversation_repository.get_message(db, request_id)
    if request is None or conversation_repository.get_member(db, request.conversation_id, user.id) is None:
        raise StyleRequestNotFoundError
    request = answerable_request(db, user, request.conversation_id, request_id)
    if (request.payload or {}).get("image_id") != str(person_image_id):
        raise ImageNotFoundError
    person = image_repository.get(db, person_image_id)
    if person is None:
        raise ImageNotFoundError
    return person, _saved_clothing_ids(db, user, clothing_ids)


# --- Saving a look ---------------------------------------------------------------------------


def _look(db: Session, user: User, message_id: uuid.UUID) -> Message:
    message = conversation_repository.get_message(db, message_id)
    if (
        message is None
        or message.kind != "styled_look"
        or message.deleted_at is not None
        or conversation_repository.get_member(db, message.conversation_id, user.id) is None
    ):
        raise LookNotFoundError
    return message


def _existing(db: Session, user: User, message_id: uuid.UUID) -> dict[int, SavedPiece]:
    rows = db.scalars(
        select(SavedPiece).where(SavedPiece.user_id == user.id, SavedPiece.look_message_id == message_id)
    )
    return {row.look_index: row for row in rows}


def _save(db: Session, user: User, message: Message, index: int, piece: dict) -> SavedPiece:
    # The fit or photo may be gone since the look was sent.
    fit_id = uuid.UUID(piece["fit_id"]) if piece.get("fit_id") else None
    if fit_id is not None and fit_repository.get(db, fit_id) is None:
        fit_id = None
    image_id = uuid.UUID(piece["image_id"]) if piece.get("image_id") else None
    if image_id is not None and image_repository.get(db, image_id) is None:
        image_id = None
    pin = piece.get("pin") or {}
    stylist = message.sender.username if message.sender else None
    saved = SavedPiece(
        user_id=user.id,
        fit_id=fit_id,
        source_username=piece.get("source_username") or stylist,
        category=piece["category"],
        name=piece["name"],
        brand=piece.get("brand"),
        color=piece.get("color"),
        url=piece.get("url"),
        image_id=image_id,
        pin_x=pin.get("x"),
        pin_y=pin.get("y"),
        zoom=bool(piece.get("zoom")) and image_id is not None,
        look_message_id=message.id,
        look_index=index,
    )
    engagement_repository.add_saved_piece(db, saved)
    return saved


def save_look_piece(db: Session, user: User, message_id: uuid.UUID, index: int) -> SavedPiece:
    """Save one piece of a styled look to the user's saved pieces. Saving it again returns the
    existing save. Raises LookNotFoundError."""
    message = _look(db, user, message_id)
    pieces = (message.payload or {}).get("pieces", [])
    if not 0 <= index < len(pieces):
        raise LookNotFoundError
    saved = _existing(db, user, message.id).get(index) or _save(db, user, message, index, pieces[index])
    db.commit()
    db.refresh(saved)
    return saved


def save_look(db: Session, user: User, message_id: uuid.UUID) -> SavedLook:
    """Save the whole look (listed with the user's saved fits). Saving it again returns the
    existing save. Raises LookNotFoundError."""
    message = _look(db, user, message_id)
    existing = db.scalar(select(SavedLook).where(SavedLook.user_id == user.id, SavedLook.message_id == message.id))
    if existing is not None:
        return existing
    payload = message.payload or {}
    tryon_image_id = payload.get("tryon_image_id")
    look = SavedLook(
        user_id=user.id,
        message_id=message.id,
        conversation_id=message.conversation_id,
        stylist_id=message.sender_id,
        note=message.body,
        tryon_image_id=uuid.UUID(tryon_image_id) if tryon_image_id else None,
        pieces=payload.get("pieces", []),
    )
    if look.tryon_image_id is not None and image_repository.get(db, look.tryon_image_id) is None:
        look.tryon_image_id = None
    db.add(look)
    db.commit()
    db.refresh(look)
    return look


def unsave_look(db: Session, user: User, look_id: uuid.UUID) -> None:
    """Raises SavedLookNotFoundError (also for someone else's)."""
    look = db.get(SavedLook, look_id)
    if look is None or look.user_id != user.id:
        raise SavedLookNotFoundError
    db.delete(look)
    db.commit()


def list_saved_looks(db: Session, user: User, *, limit: int, cursor: str | None) -> tuple[list[SavedLook], str | None]:
    """Newest first. Raises InvalidCursorError."""
    query = select(SavedLook).where(SavedLook.user_id == user.id)
    if cursor:
        created_at, look_id = decode_cursor(cursor)
        query = query.where(
            (SavedLook.created_at < created_at) | ((SavedLook.created_at == created_at) & (SavedLook.id < look_id))
        )
    rows = list(db.scalars(query.order_by(SavedLook.created_at.desc(), SavedLook.id.desc()).limit(limit + 1)))
    page = rows[:limit]
    next_cursor = encode_cursor(page[-1].created_at, page[-1].id) if len(rows) > limit and page else None
    return page, next_cursor


def saved_look_views(db: Session, looks: list[SavedLook]) -> list[SavedLookRead]:
    ids = {uuid.UUID(p["image_id"]) for look in looks for p in look.pieces or [] if p.get("image_id")}
    images = {i.id: ImageRead.model_validate(i) for i in image_repository.get_many(db, list(ids))} if ids else {}
    views = []
    for look in looks:
        pieces = []
        for piece in look.pieces or []:
            piece = dict(piece)
            image_id = piece.pop("image_id", None)
            piece["photo"] = images.get(uuid.UUID(image_id)) if image_id else None
            pieces.append(LookPieceRead.model_validate(piece))
        stylist = look.stylist if look.stylist is not None and look.stylist.is_active else None
        views.append(
            SavedLookRead(
                id=look.id,
                message_id=look.message_id,
                conversation_id=look.conversation_id,
                stylist=UserSummary.model_validate(stylist) if stylist else None,
                note=look.note,
                tryon_image=ImageRead.model_validate(look.tryon_image) if look.tryon_image else None,
                pieces=pieces,
                created_at=look.created_at,
            )
        )
    return views


def saved_look_ids(db: Session, viewer_id: uuid.UUID, message_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    """The viewer's saved looks among these messages: {message_id: saved look id}."""
    if not message_ids:
        return {}
    rows = db.execute(
        select(SavedLook.message_id, SavedLook.id).where(
            SavedLook.user_id == viewer_id, SavedLook.message_id.in_(message_ids)
        )
    )
    return {message_id: str(look_id) for message_id, look_id in rows}


def saved_look_pieces(db: Session, viewer_id: uuid.UUID, message_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict[int, str]]:
    """The viewer's saves from these looks: {message_id: {piece index: saved piece id}}."""
    if not message_ids:
        return {}
    rows = db.execute(
        select(SavedPiece.look_message_id, SavedPiece.look_index, SavedPiece.id).where(
            SavedPiece.user_id == viewer_id, SavedPiece.look_message_id.in_(message_ids)
        )
    )
    result: dict[uuid.UUID, dict[int, str]] = {}
    for message_id, index, piece_id in rows:
        result.setdefault(message_id, {})[index] = str(piece_id)
    return result
