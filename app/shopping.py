"""Finding products that look like a clothing piece, behind a small interface.

Uses Google Lens visual search through SerpApi (serpapi.com): the piece's crop is uploaded to
SerpApi's Image API and searched with the google_lens engine. Matching is best-effort: when
it isn't configured or fails, pieces just have no shop link. Tests replace get_product_finder
with a fake.
"""

import io
import logging
import re
from functools import lru_cache
from typing import Any, Protocol

from pydantic import BaseModel

from app.core.config import settings

logger = logging.getLogger(__name__)


class ProductMatch(BaseModel):
    title: str
    link: str
    source: str | None = None  # the store or site, e.g. "Uniqlo"
    thumbnail: str | None = None
    price: str | None = None  # as displayed, e.g. "$39.90"


class ProductFinder(Protocol):
    def find(self, crop_jpeg: bytes, description: str) -> list[ProductMatch]:
        """Products that look like the piece in the crop, best first. `description` is what
        the piece is (e.g. "black ribbed tank top"), used to rank lookalikes. Never raises."""
        ...


STOPWORDS = {"the", "and", "with", "for", "men", "mens", "women", "womens", "top"}
# Fit photos are of adults; Lens often offers kids' versions of the same look.
KIDS_WORDS = {"baby", "babie", "kid", "toddler", "infant", "newborn", "girl", "boy", "youth", "children"}


def _words(text: str) -> list[str]:
    """Lowercase words in order, singular-ish ("shorts" ~ "short"), for comparing titles."""
    words = []
    for word in re.findall(r"[a-z]+", text.lower()):
        if len(word) < 3 or word in STOPWORDS:
            continue
        words.append(word[:-1] if len(word) > 4 and word.endswith("s") else word)
    return words


def _relevance(description: list[str], title: str) -> int:
    """How well a title fits the piece. The last word of the description is the kind of
    garment ("short", "tank", "overshirt") and counts most: shorts shouldn't match pants."""
    title_words = set(_words(title))
    score = len(set(description) & title_words)
    if description and description[-1] in title_words:
        score += 3
    if title_words & KIDS_WORDS:
        score -= 3
    return score


def parse_matches(results: dict, description: str, limit: int) -> list[ProductMatch]:
    """Turn a google_lens response into the best few matches.

    Lens ranks by how the image looks, which can't tell shorts from trousers in a cropped
    photo, or a ribbed tank from a cashmere one. So rank by, in order:
    1. product pages priced in the local currency, then pages without a price (blogs, image
       pages), then products priced in another currency;
    2. how well the title fits the piece's description (see _relevance);
    3. Google's own order.
    """
    wanted = _words(description)
    candidates = []
    for position, result in enumerate(results.get("visual_matches") or []):
        link, title = result.get("link"), result.get("title")
        if not link or not title or not link.startswith(("https://", "http://")) or len(link) > 2048:
            continue
        price = result.get("price") or {}
        value = price.get("value") if isinstance(price, dict) else None
        value = value.strip().rstrip("*").strip() if isinstance(value, str) else None
        match = ProductMatch(
            title=title[:200],
            link=link,
            source=result.get("source"),
            thumbnail=result.get("thumbnail"),
            price=value or None,
        )
        if match.price is None:
            tier = 1
        elif settings.SHOP_MATCH_CURRENCY in match.price:
            tier = 0
        else:
            tier = 2
        candidates.append(((tier, -_relevance(wanted, title), position), match))
    candidates.sort(key=lambda candidate: candidate[0])
    return [match for _, match in candidates[:limit]]


class SerpApiLensFinder:
    def __init__(self, client: Any) -> None:
        self.client = client

    def find(self, crop_jpeg: bytes, description: str) -> list[ProductMatch]:
        # One retry: in testing, an occasional request failed and the next one worked.
        for attempt in (1, 2):
            try:
                return self._search(crop_jpeg, description)
            except Exception:
                # Never fail detection over shop links.
                logger.warning("Shop match: SerpApi request failed (attempt %s)", attempt, exc_info=True)
        return []

    def _search(self, crop_jpeg: bytes, description: str) -> list[ProductMatch]:
        upload = self.client.upload_image(
            io.BytesIO(crop_jpeg), timeout=settings.SHOP_MATCH_TIMEOUT_SECONDS
        )
        results = self.client.search(
            {
                "engine": "google_lens",
                "image_id": upload["image_id"],
                "type": "visual_matches",
                "country": settings.SHOP_MATCH_COUNTRY,
                "hl": settings.SHOP_MATCH_LANGUAGE,
            },
            timeout=settings.SHOP_MATCH_TIMEOUT_SECONDS,
        )
        if results.get("error"):
            raise RuntimeError(f"SerpApi error: {results['error']}")
        return parse_matches(dict(results), description, settings.SHOP_MATCHES_PER_ITEM)


class NoProductFinder:
    def find(self, crop_jpeg: bytes, description: str) -> list[ProductMatch]:
        return []


@lru_cache
def _build_finder() -> ProductFinder:
    import serpapi

    return SerpApiLensFinder(serpapi.Client(api_key=settings.SERPAPI_API_KEY))


def get_product_finder() -> ProductFinder:
    if not settings.SERPAPI_API_KEY:
        return NoProductFinder()
    return _build_finder()
