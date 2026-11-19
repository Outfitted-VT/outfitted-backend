import unicodedata
import uuid
from typing import Annotated, Literal, Self

from pydantic import AfterValidator, BaseModel, Field, model_validator

from app.core.config import settings
from app.schemas.user import UserSummary, UtcDatetime

KEEP_CONTROL = {"\n", "\t"}


def clean_text(value: str | None) -> str | None:
    """Drop control and invisible formatting characters (zero-width, bidi overrides) and trim."""
    if value is None:
        return None
    kept = (
        c for c in value if c in KEEP_CONTROL or unicodedata.category(c) not in ("Cc", "Cf")
    )
    return "".join(kept).strip() or None


CleanText = AfterValidator(clean_text)


class ConversationCreate(BaseModel):
    type: Literal["direct", "circle"]
    member_ids: list[uuid.UUID] = Field(min_length=1, description="Everyone except you.")
    title: Annotated[str | None, Field(max_length=80), CleanText] = None

    @model_validator(mode="after")
    def check_members(self) -> Self:
        self.member_ids = list(dict.fromkeys(self.member_ids))
        if self.type == "direct" and len(self.member_ids) != 1:
            raise ValueError("A direct chat has exactly one other member")
        if len(self.member_ids) >= settings.CIRCLE_MAX_MEMBERS:
            raise ValueError(f"A circle can have at most {settings.CIRCLE_MAX_MEMBERS} members")
        return self


class ConversationUpdate(BaseModel):
    muted: bool | None = None
    title: Annotated[str | None, Field(max_length=80), CleanText] = None


class ProductIn(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=120), CleanText]
    color: Annotated[str | None, Field(max_length=40), CleanText] = None
    price: Annotated[str | None, Field(max_length=20), CleanText] = None
    url: Annotated[str | None, Field(max_length=500, pattern=r"^https?://")] = None
    image_id: uuid.UUID | None = None


LOOK_MAX_PIECES = 12
LookCategory = Literal[
    "top", "bottom", "dress", "outerwear", "shoes", "bag", "accessory", "jewelry", "headwear", "other"
]
HttpUrl = Annotated[str | None, Field(max_length=2048, pattern=r"^https?://")]


class LookPieceIn(BaseModel):
    """One piece of a styled look, from exactly one source:

    - `saved_piece_id`: one of your saved pieces.
    - `fit_id` + `item_id`: a piece of a fit you can see (e.g. one you saved).
    - `image_id`: a photo you uploaded with `POST /images`; then `name` and `category` too.

    `name`, `brand`, `color` and `url` replace the source's own (add a shop link, for example).
    """

    saved_piece_id: uuid.UUID | None = None
    fit_id: uuid.UUID | None = None
    item_id: uuid.UUID | None = None
    image_id: uuid.UUID | None = None
    category: LookCategory | None = None
    name: Annotated[str | None, Field(max_length=100), CleanText] = None
    brand: Annotated[str | None, Field(max_length=100), CleanText] = None
    color: Annotated[str | None, Field(max_length=50), CleanText] = None
    url: HttpUrl = None

    @model_validator(mode="after")
    def check_source(self) -> Self:
        sources = [self.saved_piece_id is not None, self.fit_id is not None, self.image_id is not None]
        if sum(sources) != 1:
            raise ValueError("Give a piece exactly one of saved_piece_id, fit_id + item_id, or image_id")
        if (self.fit_id is None) != (self.item_id is None):
            raise ValueError("fit_id and item_id go together")
        if self.image_id is not None and (self.name is None or self.category is None):
            raise ValueError("An uploaded piece needs a name and a category")
        return self


class LookIn(BaseModel):
    pieces: list[LookPieceIn] = Field(min_length=1, max_length=LOOK_MAX_PIECES)
    tryon_id: uuid.UUID | None = Field(
        default=None, description="A try-on you made of the look (on the asker's photo); its result is shown."
    )


class MessageCreate(BaseModel):
    kind: Literal["text", "image", "fit_check", "product", "fit", "style_request", "styled_look"]
    body: Annotated[str | None, Field(max_length=settings.MESSAGE_MAX_LENGTH), CleanText] = None
    image_id: uuid.UUID | None = None
    question: Annotated[str | None, Field(max_length=280), CleanText] = None
    context: Annotated[str | None, Field(max_length=60), CleanText] = None
    fit_id: uuid.UUID | None = None
    product: ProductIn | None = None
    # styled_look: the style_request it answers, and the look.
    request_id: uuid.UUID | None = None
    look: LookIn | None = None
    client_id: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def check_kind(self) -> Self:
        required = {
            "text": ("body",),
            "image": ("image_id",),
            "fit_check": ("image_id", "question"),
            "product": ("product",),
            "fit": ("fit_id",),
            "style_request": (),
            "styled_look": ("request_id", "look"),
        }[self.kind]
        missing = [field for field in required if getattr(self, field) is None]
        if missing:
            raise ValueError(f"A {self.kind} message needs {', '.join(missing)}")
        return self


class VoteIn(BaseModel):
    vote: Literal["wear", "rethink"]


class VoteTally(BaseModel):
    wear: int
    rethink: int
    total: int
    wear_pct: int
    rethink_pct: int
    my_vote: str | None = None


class VoteResult(VoteTally):
    message_id: uuid.UUID
    conversation_id: uuid.UUID


class MessageRead(BaseModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    sender: UserSummary | None
    kind: str
    body: str | None
    payload: dict | None
    client_id: str | None = None
    created_at: UtcDatetime
    edited_at: UtcDatetime | None = None
    deleted_at: UtcDatetime | None = None
    votes: VoteTally | None = None


class MemberRead(BaseModel):
    user: UserSummary
    role: str
    online: bool
    last_seen_at: UtcDatetime | None
    last_read_at: UtcDatetime | None
    last_delivered_at: UtcDatetime | None


class ConversationRead(BaseModel):
    id: uuid.UUID
    type: str
    title: str | None
    created_at: UtcDatetime
    muted: bool
    unread_count: int
    members: list[MemberRead]
    last_message: MessageRead | None
    last_activity_at: UtcDatetime


class CirclePerson(BaseModel):
    user: UserSummary
    online: bool
    last_seen_at: UtcDatetime | None
    has_live_fit_check: bool
    has_active_story: bool = False
    has_unseen_story: bool = False
