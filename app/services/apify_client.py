"""
Apify integration for LIVE product data.

Two separate actors are used:
  - AMAZON_ACTOR_ID  : an Apify actor that scrapes Amazon search results
  - FLIPKART_ACTOR_ID: an Apify actor that scrapes Flipkart search results

Both are called through Apify's "run actor synchronously and get dataset
items" REST endpoint:
    POST https://api.apify.com/v2/acts/{actor_id}/run-sync-get-dataset-items

Field names in each actor's output vary depending on which public actor you
plug in (that's why AMAZON_ACTOR_ID / FLIPKART_ACTOR_ID are configurable).
The `_extract_*` methods below use tolerant, best-effort field lookups
across common key names used by popular Amazon/Flipkart Apify actors.
If your chosen actor uses different field names, adjust the FIELD_MAP
lists below - no other code needs to change.

NEVER invent data here. If a field can't be found, it is left as None and
surfaced to the user as "not available" rather than guessed.
"""
import asyncio
import logging
from typing import Any, Dict, List, Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import get_settings

logger = logging.getLogger("smartshop.apify")
settings = get_settings()

APIFY_BASE_URL = "https://api.apify.com/v2"


class ApifyUnavailableError(Exception):
    """Raised when an actor cannot be reached/timed out/misconfigured."""


def _first_present(item: Dict[str, Any], keys: List[str]) -> Optional[Any]:
    for k in keys:
        if k in item and item[k] not in (None, "", []):
            return item[k]
    return None


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        cleaned = (
            str(value)
            .replace(",", "")
            .replace("₹", "")
            .replace("Rs.", "")
            .replace("Rs", "")
            .strip()
        )
        # take leading numeric portion e.g. "4.3 out of 5" -> 4.3
        num = ""
        for ch in cleaned:
            if ch.isdigit() or ch == ".":
                num += ch
            elif num:
                break
        return float(num) if num else None
    except (ValueError, TypeError):
        return None


def _to_int(value: Any) -> Optional[int]:
    f = _to_float(value)
    return int(f) if f is not None else None


class ApifyClient:
    def __init__(self):
        self.token = settings.APIFY_API_TOKEN
        self.timeout = settings.APIFY_RUN_TIMEOUT_SECONDS

    def _configured(self) -> bool:
        return bool(self.token)

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=1, max=4),
        reraise=True,
    )
    async def _run_actor_sync(
        self, actor_id: str, run_input: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        if not self.token:
            raise ApifyUnavailableError("APIFY_API_TOKEN is not configured")
        if not actor_id:
            raise ApifyUnavailableError("Actor ID is not configured")

        # Apify's REST API path requires "username~actor-name", not
        # "username/actor-name". Accept either form in config/env and
        # normalize it here so a slash-style ID doesn't 404.
        normalized_actor_id = actor_id.replace("/", "~")
        url = f"{APIFY_BASE_URL}/acts/{normalized_actor_id}/run-sync-get-dataset-items"
        params = {"token": self.token, "clean": "true"}

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                resp = await client.post(url, params=params, json=run_input)
            except httpx.TimeoutException as exc:
                raise ApifyUnavailableError(f"Actor {actor_id} timed out") from exc
            except httpx.RequestError as exc:
                raise ApifyUnavailableError(f"Network error calling actor {actor_id}: {exc}") from exc

        if resp.status_code >= 400:
            raise ApifyUnavailableError(
                f"Actor {actor_id} returned HTTP {resp.status_code}: {resp.text[:300]}"
            )
        try:
            data = resp.json()
        except ValueError as exc:
            raise ApifyUnavailableError(f"Actor {actor_id} returned invalid JSON") from exc

        if not isinstance(data, list):
            return []
        return data

    # ---------------- Amazon ----------------

    async def search_amazon(self, query: str, max_results: int = 20) -> List[Dict[str, Any]]:
        """Returns normalized offer dicts for Amazon, or [] on failure."""
        if not settings.AMAZON_ACTOR_ID:
            logger.warning("AMAZON_ACTOR_ID not configured; skipping Amazon search")
            return []
        run_input = {
            "queries": [query],
            "country": "in",
            "maxResults": max_results,
        }
        try:
            items = await self._run_actor_sync(settings.AMAZON_ACTOR_ID, run_input)
        except ApifyUnavailableError as exc:
            logger.error("Amazon Apify actor unavailable: %s", exc)
            return []
        return [self._normalize_amazon_item(it) for it in items if it][:max_results]

    def _normalize_amazon_item(self, item: Dict[str, Any]) -> Dict[str, Any]:
        title = _first_present(item, ["title", "name", "productName"])
        url = _first_present(item, ["url", "productUrl", "link", "asinUrl"])
        image = _first_present(item, ["image_url", "thumbnailImage", "image", "imageUrl", "mainImage"])
        price = _to_float(
            _first_present(item, ["price_value", "price", "currentPrice", "priceValue", "salePrice"])
        )
        rating = _to_float(
            _first_present(item, ["rating_value", "rating", "stars", "productRating", "averageRating"])
        )
        review_count = _to_int(
            _first_present(
                item,
                ["reviews_count_value", "reviewsCount", "reviews", "totalReviews", "ratingsTotal"],
            )
        )
        asin = _first_present(item, ["asin", "productId", "id"])
        specs = _first_present(item, ["attributes", "specifications", "productDetails"]) or {}
        availability = _first_present(item, ["is_prime", "availability", "inStock", "stockStatus"])

        return {
            "platform": "amazon",
            "platform_product_id": asin,
            "title": title or "Unknown Amazon Product",
            "url": url,
            "image_url": image,
            "price": price,
            "currency": _first_present(item, ["currency_code", "currency"]) or "INR",
            "rating": rating,
            "review_count": review_count,
            "availability": str(availability) if availability is not None else None,
            "raw_specifications": specs if isinstance(specs, dict) else {},
            "raw_payload": item,
        }

    # ---------------- Flipkart ----------------

    async def search_flipkart(self, query: str, max_results: int = 20) -> List[Dict[str, Any]]:
        """Returns normalized offer dicts for Flipkart, or [] on failure."""
        if not settings.FLIPKART_ACTOR_ID:
            logger.warning("FLIPKART_ACTOR_ID not configured; skipping Flipkart search")
            return []
        run_input = {
            "keyword": query,
            "results_wanted": max_results,
        }
        try:
            items = await self._run_actor_sync(settings.FLIPKART_ACTOR_ID, run_input)
        except ApifyUnavailableError as exc:
            logger.error("Flipkart Apify actor unavailable: %s", exc)
            return []
        return [self._normalize_flipkart_item(it) for it in items if it][:max_results]

    def _normalize_flipkart_item(self, item: Dict[str, Any]) -> Dict[str, Any]:
        title = _first_present(item, ["title", "name", "productName"])
        url = _first_present(item, ["url", "productUrl", "link"])
        image = _first_present(item, ["image_url", "image", "imageUrl", "thumbnail"])
        price = _to_float(_first_present(item, ["price", "currentPrice", "sellingPrice", "priceValue"]))
        rating = _to_float(_first_present(item, ["rating", "productRating", "averageRating"]))
        review_count = _to_int(
            _first_present(
                item,
                ["review_count", "rating_count", "reviewsCount", "reviews", "totalReviews", "numberOfReviews"],
            )
        )
        pid = _first_present(item, ["id", "item_id", "listing_id", "pid", "productId"])
        specs = _first_present(item, ["specifications", "key_specs", "highlights", "attributes"]) or {}
        availability = _first_present(
            item, ["availability_status", "is_available", "availability", "inStock", "stockStatus"]
        )

        # Some actors return specs/highlights as a list of strings; normalize to dict
        if isinstance(specs, list):
            specs = {f"highlight_{i+1}": v for i, v in enumerate(specs)}

        return {
            "platform": "flipkart",
            "platform_product_id": pid,
            "title": title or "Unknown Flipkart Product",
            "url": url,
            "image_url": image,
            "price": price,
            "currency": "INR",
            "rating": rating,
            "review_count": review_count,
            "availability": str(availability) if availability is not None else None,
            "raw_specifications": specs if isinstance(specs, dict) else {},
            "raw_payload": item,
        }

    # ---------------- Combined ----------------

    async def search_both(self, query: str, max_results: int = 20):
        """
        Runs Amazon + Flipkart searches concurrently. Each platform fails
        independently - if one is down/misconfigured, the other's results
        still come back, plus a warning message for the frontend.
        """
        results = await asyncio.gather(
            self.search_amazon(query, max_results),
            self.search_flipkart(query, max_results),
            return_exceptions=True,
        )
        amazon_items, flipkart_items = results
        warnings = []

        if isinstance(amazon_items, Exception):
            warnings.append("Amazon results are currently unavailable (service error).")
            amazon_items = []
        elif not amazon_items:
            warnings.append("No Amazon results found for this query.")

        if isinstance(flipkart_items, Exception):
            warnings.append("Flipkart results are currently unavailable (service error).")
            flipkart_items = []
        elif not flipkart_items:
            warnings.append("No Flipkart results found for this query.")

        return amazon_items, flipkart_items, warnings


apify_client = ApifyClient()