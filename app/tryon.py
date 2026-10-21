"""Virtual try-on image generation behind a small interface, so the model can be swapped.

Two Google models are supported, chosen by TRYON_MODEL:
- Gemini image models (default, e.g. "gemini-3.1-flash-image"): prompted with both photos.
- "virtual-try-on-001": the dedicated try-on model. Deprecated; support ends in 2027.

Both run on Gemini Enterprise Agent Platform (previously Vertex AI) and authenticate with
Application Default Credentials. Tests replace get_tryon_generator with a fake.
"""

import logging
from functools import lru_cache
from typing import Any, Protocol

from app.core.config import settings

logger = logging.getLogger(__name__)

# Inputs are sent as JPEG (see app.core.images.to_jpeg).
INPUT_MIME_TYPE = "image/jpeg"

GEMINI_PROMPT = (
    "The first image is a photo of a person. The second image shows one or more clothing "
    "items, either on their own or worn by someone else. Edit the first photo so the person "
    "is wearing exactly the clothing items from the second image. "
    "Replace only the clothes those items take the place of (for example, a top replaces the "
    "person's current top) and keep every other piece of clothing the person is wearing "
    "unchanged. Each item appears once: do not layer a copy of it, and do not add any clothing "
    "that isn't in one of the two images. Reproduce each item's color, pattern, material, and "
    "details faithfully, worn naturally and fitted to the person's body, and worn the way the "
    "second image shows it (for example, a buttoned shirt stays buttoned). "
    "Never show more of the person's body or skin than the first photo does. "
    "Keep the person's face, hair, skin tone, body shape, pose, the background, the lighting, "
    "and the framing exactly as in the first photo. Do not add any text."
)


class TryOnError(Exception):
    """Base class. The message is safe to show to users."""


class TryOnUnavailableError(TryOnError):
    """Try-on isn't configured, or the model couldn't be reached. Worth retrying later."""


class TryOnBlockedError(TryOnError):
    """The model refused these photos (safety filters) or returned no image."""


class TryOnGenerator(Protocol):
    def generate(self, person_jpeg: bytes, outfit_jpeg: bytes) -> bytes:
        """Return the generated image (PNG or JPEG bytes) of the person wearing the outfit."""
        ...


def _make_client() -> Any:
    from google import genai
    from google.genai import types

    return genai.Client(
        enterprise=True,
        project=settings.GOOGLE_CLOUD_PROJECT,
        location=settings.tryon_location,
        http_options=types.HttpOptions(timeout=settings.TRYON_TIMEOUT_SECONDS * 1000),
    )


def _call(fn: Any) -> Any:
    """Run an SDK call, turning Google's errors into TryOnErrors."""
    from google.auth.exceptions import GoogleAuthError
    from google.genai import errors

    try:
        return fn()
    except GoogleAuthError:
        logger.exception("Try-on: Google credentials are missing or invalid")
        raise TryOnUnavailableError("Try-on is temporarily unavailable") from None
    except errors.ClientError as error:
        if error.code == 429:
            logger.warning("Try-on: Google quota exceeded: %s", error)
            raise TryOnUnavailableError("Try-on is busy right now. Please try again shortly.") from None
        if error.code == 400:
            # Bad or refused input, e.g. a photo the model won't process.
            logger.info("Try-on: request rejected: %s", error)
            raise TryOnBlockedError("We couldn't create a try-on from these photos") from None
        logger.exception("Try-on: request failed")
        raise TryOnUnavailableError("Try-on is temporarily unavailable") from None
    except (errors.ServerError, errors.APIError, OSError):
        logger.exception("Try-on: request failed")
        raise TryOnUnavailableError("Try-on is temporarily unavailable") from None


class GeminiImageGenerator:
    """Gemini image model, prompted with the person photo then the outfit photo."""

    def __init__(self, client: Any, model: str) -> None:
        self.client = client
        self.model = model

    def generate(self, person_jpeg: bytes, outfit_jpeg: bytes) -> bytes:
        from google.genai import types

        response = _call(
            lambda: self.client.models.generate_content(
                model=self.model,
                contents=[
                    types.Part.from_bytes(data=person_jpeg, mime_type=INPUT_MIME_TYPE),
                    types.Part.from_bytes(data=outfit_jpeg, mime_type=INPUT_MIME_TYPE),
                    GEMINI_PROMPT,
                ],
                config=types.GenerateContentConfig(
                    response_modalities=["IMAGE"], candidate_count=1
                ),
            )
        )
        for candidate in response.candidates or []:
            for part in (candidate.content.parts if candidate.content else None) or []:
                if part.inline_data and part.inline_data.data:
                    return part.inline_data.data

        # No image: blocked by safety filters, or the model declined.
        feedback = getattr(response, "prompt_feedback", None)
        reasons = [getattr(feedback, "block_reason", None)] + [
            c.finish_reason for c in response.candidates or []
        ]
        logger.info("Try-on: %s returned no image (%s)", self.model, reasons)
        raise TryOnBlockedError("We couldn't create a try-on from these photos")


class VirtualTryOnGenerator:
    """The dedicated virtual-try-on-001 model (person image + one product image)."""

    def __init__(self, client: Any, model: str) -> None:
        self.client = client
        self.model = model

    def generate(self, person_jpeg: bytes, outfit_jpeg: bytes) -> bytes:
        from google.genai import types

        response = _call(
            lambda: self.client.models.recontext_image(
                model=self.model,
                source=types.RecontextImageSource(
                    person_image=types.Image(image_bytes=person_jpeg, mime_type=INPUT_MIME_TYPE),
                    product_images=[
                        types.ProductImage(
                            product_image=types.Image(
                                image_bytes=outfit_jpeg, mime_type=INPUT_MIME_TYPE
                            )
                        )
                    ],
                ),
                config=types.RecontextImageConfig(number_of_images=1),
            )
        )
        for generated in response.generated_images or []:
            if generated.image and generated.image.image_bytes:
                return generated.image.image_bytes

        reasons = [g.rai_filtered_reason for g in response.generated_images or []]
        logger.info("Try-on: %s returned no image (%s)", self.model, reasons)
        raise TryOnBlockedError("We couldn't create a try-on from these photos")


class UnavailableGenerator:
    def __init__(self, message: str) -> None:
        self.message = message

    def generate(self, person_jpeg: bytes, outfit_jpeg: bytes) -> bytes:
        raise TryOnUnavailableError(self.message)


@lru_cache
def _build_generator() -> TryOnGenerator:
    client = _make_client()
    if settings.TRYON_MODEL.startswith("virtual-try-on"):
        return VirtualTryOnGenerator(client, settings.TRYON_MODEL)
    return GeminiImageGenerator(client, settings.TRYON_MODEL)


def get_tryon_generator() -> TryOnGenerator:
    if not settings.GOOGLE_CLOUD_PROJECT:
        return UnavailableGenerator("Try-on isn't set up on this server")
    try:
        # Cached once built. A failure isn't cached, so fixing credentials needs no restart.
        return _build_generator()
    except Exception:
        logger.exception("Try-on: couldn't create the Google client (check credentials)")
        return UnavailableGenerator("Try-on is temporarily unavailable")
