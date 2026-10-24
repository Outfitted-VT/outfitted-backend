import uuid
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from app.schemas.user import UtcDatetime


def _strip(v: str) -> str:
    return v.strip()


TrimmedStr = Annotated[str, AfterValidator(_strip)]
GarmentCategory = Literal["tops", "bottoms", "dresses", "outerwear", "shoes", "other"]
FitFeeling = Literal["perfect", "snug", "oversized"]
TargetFitPref = Literal["standard", "relaxed", "snug"]


class ReferenceGarmentCreate(BaseModel):
    brand: Annotated[TrimmedStr, Field(min_length=1, max_length=80, examples=["Levi's"])]
    category: GarmentCategory
    item_name: Annotated[TrimmedStr, Field(min_length=1, max_length=120, examples=["501 Original Fit"])]
    size: Annotated[TrimmedStr, Field(min_length=1, max_length=30, examples=["30W 32L"])]
    fit_feeling: FitFeeling = "perfect"
    is_favorite: bool = True


class ReferenceGarmentRead(BaseModel):
    id: uuid.UUID
    brand: str
    category: GarmentCategory
    item_name: str
    size: str
    fit_feeling: FitFeeling
    is_favorite: bool
    created_at: UtcDatetime

    model_config = ConfigDict(from_attributes=True)


class TrueSizePassportRead(BaseModel):
    user_id: uuid.UUID
    benchmarks_count: int
    top_brands: list[str]
    items: list[ReferenceGarmentRead]
    calibrated_baseline: dict[str, str] = Field(
        description="User's unified baseline anchor across categories (e.g. tops: M, bottoms: 30W)."
    )


class SizeTranslateRequest(BaseModel):
    target_brand: Annotated[TrimmedStr, Field(min_length=1, max_length=80, examples=["Zara"])]
    category: GarmentCategory
    target_item_fit_pref: TargetFitPref = "standard"
    target_item_name: str | None = Field(default=None, max_length=120, examples=["Textured Knit Cardigan"])
    product_url: str | None = None


class SizeTranslateResponse(BaseModel):
    target_brand: str
    category: GarmentCategory
    recommended_size: str
    confidence_score: int = Field(ge=50, le=99, description="Confidence percentage.")
    alternative_size: str | None = None
    brand_calibration_note: str
    fabric_stretch_advice: str
    matched_reference_pieces: list[str]
    avoided_return_risk: str
