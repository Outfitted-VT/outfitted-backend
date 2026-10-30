"""Validating and normalizing uploaded images."""

import io
import warnings
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFilter, ImageOps, UnidentifiedImageError

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


def crop_jpeg(jpeg: bytes, box: list[int], *, padding: float = 0.08, max_side: int = 800) -> bytes:
    """Crop a JPEG to a [ymin, xmin, ymax, xmax] box scaled 0-1000, with some padding around it.

    Used to search for one piece of an outfit. The result is small (well under 500 KB).
    """
    image = Image.open(io.BytesIO(jpeg)).convert("RGB")
    ymin, xmin, ymax, xmax = (min(max(v, 0), 1000) / 1000 for v in box)
    pad_y, pad_x = (ymax - ymin) * padding, (xmax - xmin) * padding
    left = max(0, int((xmin - pad_x) * image.width))
    top = max(0, int((ymin - pad_y) * image.height))
    right = min(image.width, int((xmax + pad_x) * image.width))
    bottom = min(image.height, int((ymax + pad_y) * image.height))
    crop = image.crop((left, top, right, bottom))
    crop.thumbnail((max_side, max_side))
    output = io.BytesIO()
    crop.save(output, format="JPEG", quality=85)
    return output.getvalue()


def blur_regions(data: bytes, boxes: list[list[int]], *, padding: float = 0.3) -> ProcessedImage:
    """Blur [ymin, xmin, ymax, xmax] boxes (scaled 0-1000) of a stored image, e.g. faces.

    Each region is pixelated before it's blurred, so no detail survives to be sharpened back,
    and is pasted through a soft oval so the edge blends in. Re-encoded as WebP like uploads.
    """
    image = Image.open(io.BytesIO(data))
    image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
    for box in boxes:
        ymin, xmin, ymax, xmax = (min(max(v, 0), 1000) / 1000 for v in box)
        pad_y, pad_x = (ymax - ymin) * padding, (xmax - xmin) * padding
        left = max(0, int((xmin - pad_x) * image.width))
        top = max(0, int((ymin - pad_y) * image.height))
        right = min(image.width, int((xmax + pad_x) * image.width))
        bottom = min(image.height, int((ymax + pad_y) * image.height))
        width, height = right - left, bottom - top
        if width < 2 or height < 2:
            continue

        region = image.crop((left, top, right, bottom))
        blocks = (8, max(1, round(8 * height / width)))
        obscured = region.resize(blocks, Image.Resampling.BILINEAR).resize(
            (width, height), Image.Resampling.BILINEAR
        )
        obscured = obscured.filter(ImageFilter.GaussianBlur(max(width, height) / 16))

        mask = Image.new("L", (width, height), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, width - 1, height - 1), fill=255)
        mask = mask.filter(ImageFilter.GaussianBlur(min(width, height) / 30))
        image.paste(obscured, (left, top), mask)

    output = io.BytesIO()
    image.save(output, format="WEBP", quality=85)
    return ProcessedImage(data=output.getvalue(), width=image.width, height=image.height)
