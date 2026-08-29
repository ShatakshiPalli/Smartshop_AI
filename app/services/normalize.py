"""
Turns raw Apify offer dicts (one per platform listing) into canonical
Product rows with linked PlatformOffer rows, so the same real-world
product appearing on both Amazon and Flipkart is merged into ONE Product
with two offers - enabling cross-platform comparison.

Matching is title-similarity based (no ML needed for this pass): titles are
normalized (lowercased, punctuation stripped, common stopwords/marketing
words removed) and compared with a token-overlap (Jaccard) score. This is
deliberately conservative - a false merge is worse than a missed merge.
"""
import re
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models import PlatformOffer, Product

STOPWORDS = {
    "with", "and", "for", "the", "a", "an", "of", "in", "on", "new",
    "genuine", "original", "pack", "combo", "set",
}

DESCRIPTOR_WORDS = {
    "wireless", "bluetooth", "corded", "black", "white", "blue", "green", "red",
    "silver", "grey", "gray", "pink", "brown", "gold", "portable", "smart", "ultra",
    "series", "edition", "model", "latest", "new", "premium", "basic", "pro",
    "inch", "inchs", "cm", "mm", "lbs", "kg", "pack", "single", "pair",
}

MATCH_THRESHOLD = 0.55


def _token_set(title: str) -> set[str]:
    return set(normalize_title(title).split())


def _model_tokens(title: str) -> set[str]:
    tokens = []
    for token in normalize_title(title).split():
        if any(ch.isdigit() for ch in token) and len(token) >= 2:
            tokens.append(token)
            continue
        if len(token) <= 3 and any(ch.isdigit() for ch in title):
            tokens.append(token)
    return set(tokens)


def _core_tokens(title: str) -> set[str]:
    return {token for token in _token_set(title) if token not in DESCRIPTOR_WORDS and len(token) > 1}


def normalize_title(title: str) -> str:
    title = title.lower()
    title = re.sub(r"[^a-z0-9\s]", " ", title)
    tokens = [t for t in title.split() if t not in STOPWORDS and len(t) > 1]
    return " ".join(tokens)


def _similarity(a: str, b: str) -> float:
    a_tokens, b_tokens = set(a.split()), set(b.split())
    if not a_tokens or not b_tokens:
        return 0.0
    jaccard = len(a_tokens & b_tokens) / len(a_tokens | b_tokens)
    seq_ratio = SequenceMatcher(None, a, b).ratio()
    return 0.6 * jaccard + 0.4 * seq_ratio


def _pair_match_score(title_a: str, title_b: str) -> float:
    norm_a = normalize_title(title_a)
    norm_b = normalize_title(title_b)
    score = _similarity(norm_a, norm_b)

    model_a = _model_tokens(title_a)
    model_b = _model_tokens(title_b)
    if model_a and model_b and model_a & model_b:
        score += 0.25

    core_a = _core_tokens(title_a)
    core_b = _core_tokens(title_b)
    if core_a and core_b and core_a & core_b:
        score += 0.10

    return min(score, 1.0)


def guess_brand(title: str) -> Optional[str]:
    known_brands = [
        "hp", "dell", "lenovo", "asus", "acer", "apple", "msi", "samsung",
        "mi", "xiaomi", "oneplus", "realme", "boat", "sony", "lg", "jbl",
        "noise", "redmi", "vivo", "oppo",
    ]
    lowered = title.lower()
    for brand in known_brands:
        if re.search(rf"\b{brand}\b", lowered):
            return brand.upper() if len(brand) <= 3 else brand.capitalize()
    return title.split()[0].capitalize() if title else None


def dedupe_and_merge(
    db: Session,
    amazon_offers: List[Dict[str, Any]],
    flipkart_offers: List[Dict[str, Any]],
    category_hint: Optional[str] = None,
) -> List[Product]:
    """
    Groups offers into canonical products, persists them, and returns the
    resulting Product ORM objects (with .offers populated).
    """
    all_offers = [(o, normalize_title(o["title"])) for o in amazon_offers if o.get("title")]
    all_offers += [(o, normalize_title(o["title"])) for o in flipkart_offers if o.get("title")]

    groups: List[List[Tuple[Dict[str, Any], str]]] = []
    for offer, norm_title in all_offers:
        placed = False
        for group in groups:
            rep_norm_title = group[0][1]
            # only merge across DIFFERENT platforms - two Amazon listings
            # with similar titles are likely variants, not the same product
            if any(g[0]["platform"] == offer["platform"] for g in group):
                continue
            if _pair_match_score(offer["title"], group[0][0]["title"]) >= MATCH_THRESHOLD:
                group.append((offer, norm_title))
                placed = True
                break
        if not placed:
            groups.append([(offer, norm_title)])

    products: List[Product] = []
    for group in groups:
        best_offer = max(
            group, key=lambda g: (g[0].get("review_count") or 0, g[0].get("rating") or 0)
        )[0]
        title = best_offer["title"]
        brand = guess_brand(title)
        merged_specs: Dict[str, Any] = {}
        for offer, _ in group:
            if isinstance(offer.get("raw_specifications"), dict):
                merged_specs.update(offer["raw_specifications"])

        product = Product(
            canonical_title=title,
            brand=brand,
            category=category_hint,
            normalized_key=group[0][1],
            specifications=merged_specs,
            primary_image_url=best_offer.get("image_url"),
        )
        db.add(product)
        db.flush()  # get product.id without full commit

        for offer, _ in group:
            db.add(
                PlatformOffer(
                    product_id=product.id,
                    platform=offer["platform"],
                    platform_product_id=offer.get("platform_product_id"),
                    title=offer["title"],
                    url=offer.get("url") or "",
                    image_url=offer.get("image_url"),
                    price=offer.get("price"),
                    currency=offer.get("currency", "INR"),
                    rating=offer.get("rating"),
                    review_count=offer.get("review_count"),
                    availability=offer.get("availability"),
                    raw_specifications=offer.get("raw_specifications") or {},
                    raw_payload=offer.get("raw_payload") or {},
                )
            )
        products.append(product)

    db.commit()
    for p in products:
        db.refresh(p)
    return products
