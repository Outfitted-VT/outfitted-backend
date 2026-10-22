"""Detecting the clothing pieces in a photo, behind a small interface so the model can be swapped.

Uses a Gemini model that reads images (DETECTION_MODEL) on Gemini Enterprise Agent Platform,
with the same project and credentials as try-on. The model returns structured JSON: one entry
per piece, with a bounding box we turn into a pin on the photo. Tests replace
get_garment_detector with a fake.
"""

import logging
from functools import lru_cache
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

from app.core.config import settings

logger = logging.getLogger(__name__)

Category = Literal[
    "top", "bottom", "dress", "outerwear", "shoes", "bag", "accessory", "jewelry", "headwear", "other"
]

PROMPT = (
    "You catalog outfits for a fashion app. List every clothing item, pair of shoes, and "
    "accessory worn or carried by the main person in this photo. Ignore items in the "
    "background or on other people. If the photo shows clothing on its own (no person), list "
    "those items.\n"
    "For each item:\n"
    "- category: the closest match from the allowed list. Coats, jackets, blazers and "
    "overshirts worn open over another top are outerwear.\n"
    "- name: a short, specific description a shopper would recognize, 2-6 words, without the "
    "color (e.g. 'oversized corduroy overshirt', 'straight-leg jeans', 'chunky leather loafers').\n"
    "- color: the main color in plain words (e.g. 'mustard yellow', 'light-wash blue').\n"
    "- pattern, material, silhouette: only if you can tell from the photo, otherwise null.\n"
    "- box_2d: the item's bounding box as [ymin, xmin, ymax, xmax] scaled 0-1000.\n"
    "Never guess brands. List each item once. Also give occasion_tags (where you'd wear this "
    "outfit, e.g. 'casual', 'office', 'date night', 'gym') and style_tags (the outfit's style, "
    "e.g. 'streetwear', 'minimalist', 'preppy'), 1-4 of each, lowercase."
)


class DetectedPiece(BaseModel):
    category: Category
    name: str
    color: str | None = None
    pattern: str | None = None
    material: str | None = None
    silhouette: str | None = Field(default=None, description="How it fits, e.g. 'oversized'.")
    box_2d: list[int] | None = Field(default=None, description="[ymin, xmin, ymax, xmax], 0-1000.")


class Detection(BaseModel):
    items: list[DetectedPiece] = []
    occasion_tags: list[str] = []
    style_tags: list[str] = []


class DetectionUnavailableError(Exception):
    """Detection isn't configured, or the model couldn't be reached. The message is safe to show."""


class GarmentDetector(Protocol):
    def detect(self, image_jpeg: bytes) -> Detection: ...


class GeminiGarmentDetector:
    def __init__(self, client: Any, model: str) -> None:
        self.client = client
        self.model = model

    def detect(self, image_jpeg: bytes) -> Detection:
        from google.auth.exceptions import GoogleAuthError
        from google.genai import errors, types

        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=[types.Part.from_bytes(data=image_jpeg, mime_type="image/jpeg"), PROMPT],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=Detection,
                    temperature=0.2,
                ),
            )
        except errors.ClientError as error:
            if error.code == 400:
                # A photo the model won't process: nothing to suggest.
                logger.info("Detection: request rejected: %s", error)
                return Detection()
            logger.warning("Detection: request failed: %s", error)
            raise DetectionUnavailableError("Piece detection is temporarily unavailable") from None
        except (GoogleAuthError, errors.APIError, OSError):
            logger.exception("Detection: request failed")
            raise DetectionUnavailableError("Piece detection is temporarily unavailable") from None

        if isinstance(response.parsed, Detection):
            return response.parsed
        # Blocked by safety filters, or output that didn't match the schema.
        logger.info("Detection: %s returned no usable result", self.model)
        return Detection()


class UnavailableDetector:
    def __init__(self, message: str) -> None:
        self.message = message

    def detect(self, image_jpeg: bytes) -> Detection:
        raise DetectionUnavailableError(self.message)


def _make_client() -> Any:
    from google import genai
    from google.genai import types

    return genai.Client(
        enterprise=True,
        project=settings.GOOGLE_CLOUD_PROJECT,
        location=settings.DETECTION_LOCATION,
        http_options=types.HttpOptions(timeout=settings.DETECTION_TIMEOUT_SECONDS * 1000),
    )


@lru_cache
def _build_detector() -> GarmentDetector:
    return GeminiGarmentDetector(_make_client(), settings.DETECTION_MODEL)


def get_garment_detector() -> GarmentDetector:
    if not settings.GOOGLE_CLOUD_PROJECT:
        return UnavailableDetector("Piece detection isn't set up on this server")
    try:
        # Cached once built. A failure isn't cached, so fixing credentials needs no restart.
        return _build_detector()
    except Exception:
        logger.exception("Detection: couldn't create the Google client (check credentials)")
        return UnavailableDetector("Piece detection is temporarily unavailable")
