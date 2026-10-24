import uuid
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from app.schemas.user import UtcDatetime


def _strip(v: str) -> str:
    return v.strip()


TrimmedStr = Annotated[str, AfterValidator(_strip)]
ImpactActionType = Literal[
    "size_corrected",
    "avoided_bad_cut",
    "fit_check_voted_rethink",
    "confirmed_first_try",
    "stolen_from_friend",
]


class ImpactRecordCreate(BaseModel):
    item_name: Annotated[TrimmedStr, Field(min_length=1, max_length=140, examples=["Oversized Wool Trench"])]
    brand: str | None = Field(default=None, max_length=80, examples=["Aritzia"])
    category: str | None = Field(default=None, max_length=40, examples=["outerwear"])
    estimated_price: float = Field(default=75.0, ge=1.0, le=5000.0)
    action_type: ImpactActionType = "size_corrected"
    fit_id: uuid.UUID | None = None
    notes: str | None = Field(default=None, max_length=500)


class ImpactRecordRead(BaseModel):
    id: uuid.UUID
    item_name: str
    brand: str | None
    category: str | None
    estimated_price: float
    action_type: ImpactActionType
    dollars_saved: float
    co2_saved_kg: float
    notes: str | None
    created_at: UtcDatetime

    model_config = ConfigDict(from_attributes=True)


class UserImpactSummary(BaseModel):
    user_id: uuid.UUID
    total_dollars_saved: float = Field(description="Cumulative estimated dollars saved.")
    returns_prevented_count: int = Field(description="Number of ill-fitting returns averted.")
    post_office_trips_avoided: int = Field(description="Number of physical return trips spared.")
    co2_kg_saved: float = Field(description="Estimated reduction in return shipping emissions.")
    milestone_badge: str = Field(description="Gamified status badge.")
    milestone_progress_pct: int = Field(ge=0, le=100)
    recent_saves: list[ImpactRecordRead]
