"""Validating and normalizing uploaded images."""

import io
import warnings
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError

ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
MAX_DIMENSION = 2048
# Refuse images that decode to more pixels than this (decompression bombs).
MAX_PIXELS = 50_000_000
OUTPUT_CONTENT_TYPE = "image/webp"
OUTPUT_EXTENSION = "webp"


class InvalidImageError(Exception):
    pass


@dataclass(frozen=True)
class ProcessedImage:
    data: bytes
    width: int
    height: int


def process_image(data: bytes) -> ProcessedImage:
    """Validate an upload and re-encode it as WebP.

    Re-encoding strips all metadata, including EXIF GPS location. Orientation from EXIF
    is applied first so photos aren't sideways, and large images are scaled down.
    WebP keeps transparency, which matters for garment cut-outs later.
    """
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            image = Image.open(io.BytesIO(data))
            if image.format not in ALLOWED_FORMATS:
                raise InvalidImageError("Image must be JPEG, PNG, or WebP")
            if image.width * image.height > MAX_PIXELS:
                raise InvalidImageError("Image dimensions are too large")
            image.load()
    except InvalidImageError:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise InvalidImageError("File is not a supported image") from None
    except OSError:
        raise InvalidImageError("Image file is corrupt or truncated") from None

    image = ImageOps.exif_transpose(image)
    image.thumbnail((MAX_DIMENSION, MAX_DIMENSION))
    if image.mode not in ("RGB", "RGBA"):
        image = image.convert("RGBA" if "A" in image.getbands() else "RGB")

    output = io.BytesIO()
    image.save(output, format="WEBP", quality=85)
    return ProcessedImage(data=output.getvalue(), width=image.width, height=image.height)


def to_jpeg(data: bytes) -> bytes:
    """Convert a stored image to JPEG for models that only accept JPEG or PNG.

    Transparent areas (e.g. a garment cut-out) become white rather than black.
    """
    image = Image.open(io.BytesIO(data))
    if image.mode in ("RGBA", "LA", "P"):
        image = image.convert("RGBA")
        background = Image.new("RGB", image.size, "white")
        background.paste(image, mask=image.getchannel("A"))
        image = background
    elif image.mode != "RGB":
        image = image.convert("RGB")
    output = io.BytesIO()
    image.save(output, format="JPEG", quality=90)
    return output.getvalue()
