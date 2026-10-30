"""Finding the faces in a photo, so a try-on can be posted with the face blurred.

Uses the same Gemini model, project, and credentials as piece detection (DETECTION_MODEL).
The model returns a bounding box per face. Tests replace get_face_locator with a fake.
"""

import logging
from functools import lru_cache
from typing import Any, Protocol

from pydantic import BaseModel, Field

from app.core.config import settings
from app.garments import _make_client

logger = logging.getLogger(__name__)

PROMPT = (
    "Find every human face in this photo, including faces turned to the side, partly covered "
    "by hair, hats, or sunglasses, or small in the frame. For each face, give box_2d: the "
    "bounding box as [ymin, xmin, ymax, xmax] scaled 0-1000, covering the whole face from the "
    "hairline to the chin and ear to ear. If there are no faces, return an empty list."
)


class Face(BaseModel):
    box_2d: list[int] = Field(description="[ymin, xmin, ymax, xmax], 0-1000.")


class Faces(BaseModel):
    faces: list[Face] = []


class FaceLocatorUnavailableError(Exception):
    """Face finding isn't configured, or the model couldn't be reached. Safe to show."""


class FaceLocator(Protocol):
    def locate(self, image_jpeg: bytes) -> list[list[int]]: ...


def _valid(box: list[int]) -> bool:
    if len(box) != 4:
        return False
    ymin, xmin, ymax, xmax = box
    return 0 <= ymin < ymax <= 1000 and 0 <= xmin < xmax <= 1000


class GeminiFaceLocator:
    def __init__(self, client: Any, model: str) -> None:
        self.client = client
        self.model = model

    def locate(self, image_jpeg: bytes) -> list[list[int]]:
        from google.auth.exceptions import GoogleAuthError
        from google.genai import errors, types

        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=[types.Part.from_bytes(data=image_jpeg, mime_type="image/jpeg"), PROMPT],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=Faces,
                    temperature=0,
                ),
            )
        except errors.ClientError as error:
            if error.code == 400:
                # A photo the model won't process: no faces found.
                logger.info("Faces: request rejected: %s", error)
                return []
            logger.warning("Faces: request failed: %s", error)
            raise FaceLocatorUnavailableError("Face blurring is temporarily unavailable") from None
        except (GoogleAuthError, errors.APIError, OSError):
            logger.exception("Faces: request failed")
            raise FaceLocatorUnavailableError("Face blurring is temporarily unavailable") from None

        if isinstance(response.parsed, Faces):
            return [face.box_2d for face in response.parsed.faces if _valid(face.box_2d)]
        # Blocked by safety filters, or output that didn't match the schema.
        logger.info("Faces: %s returned no usable result", self.model)
        return []


class UnavailableFaceLocator:
    def __init__(self, message: str) -> None:
        self.message = message

    def locate(self, image_jpeg: bytes) -> list[list[int]]:
        raise FaceLocatorUnavailableError(self.message)


@lru_cache
def _build_locator() -> FaceLocator:
    return GeminiFaceLocator(_make_client(), settings.DETECTION_MODEL)


def get_face_locator() -> FaceLocator:
    if not settings.GOOGLE_CLOUD_PROJECT:
        return UnavailableFaceLocator("Face blurring isn't set up on this server")
    try:
        # Cached once built. A failure isn't cached, so fixing credentials needs no restart.
        return _build_locator()
    except Exception:
        logger.exception("Faces: couldn't create the Google client (check credentials)")
        return UnavailableFaceLocator("Face blurring is temporarily unavailable")
