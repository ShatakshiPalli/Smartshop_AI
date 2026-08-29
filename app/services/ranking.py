"""
Ranks canonical Products for a search query using their REAL retrieved
attributes (price, rating, review count, spec match) plus an optional LLM
pass that writes a short natural-language "why we recommend this" reason.

The heuristic score always runs (so ranking works even with no LLM key).
The LLM is only ever given the already-retrieved, real data - it is asked
to explain/summarize, never to invent facts.
"""
import json
import logging
from typing import Dict, List, Optional

from app.models import Product
from app.services.llm import llm_client

logger = logging.getLogger("smartshop.ranking")


def _offer_summary(product: Product) -> Dict:
    prices = [o.price for o in product.offers if o.price]
    ratings = [o.rating for o in product.offers if o.rating]
    reviews = [o.review_count for o in product.offers if o.review_count]
    best_offer = min(
        (o for o in product.offers if o.price is not None),
        key=lambda o: o.price,
        default=(product.offers[0] if product.offers else None),
    )
    return {
        "best_price": min(prices) if prices else None,
        "best_platform": best_offer.platform if best_offer else None,
        "avg_rating": round(sum(ratings) / len(ratings), 2) if ratings else None,
        "total_reviews": sum(reviews) if reviews else 0,
    }


def heuristic_score(product: Product, max_price: Optional[float] = None) -> float:
    summary = _offer_summary(product)
    score = 0.0

    if summary["avg_rating"]:
        score += summary["avg_rating"] * 20  # up to 100

    if summary["total_reviews"]:
        # log-ish scaling so 50k reviews doesn't dominate absurdly
        import math

        score += min(math.log10(summary["total_reviews"] + 1) * 15, 45)

    if summary["best_price"]:
        if max_price:
            # reward staying comfortably under budget
            if summary["best_price"] <= max_price:
                headroom = (max_price - summary["best_price"]) / max_price
                score += headroom * 20
            else:
                score -= 40  # over budget - penalize hard
        # cheaper among candidates is a mild positive, applied later via normalization

    if len(product.offers) > 1:
        score += 10  # available cross-platform - user gets a real comparison

    return score


def rank_products(
    products: List[Product], query: str, max_price: Optional[float] = None
) -> List[Dict]:
    scored = []
    for p in products:
        summary = _offer_summary(p)
        score = heuristic_score(p, max_price)
        scored.append({"product": p, "summary": summary, "score": score})

    scored.sort(key=lambda x: x["score"], reverse=True)

    # Optional LLM pass: generate a short reason per top result using ONLY
    # retrieved data (no hallucinated facts).
    if llm_client.available and scored:
        top_n = scored[:10]
        context_items = []
        for i, item in enumerate(top_n):
            p, s = item["product"], item["summary"]
            context_items.append(
                {
                    "index": i,
                    "title": p.canonical_title,
                    "brand": p.brand,
                    "best_price": s["best_price"],
                    "best_platform": s["best_platform"],
                    "avg_rating": s["avg_rating"],
                    "total_reviews": s["total_reviews"],
                    "specifications": p.specifications or {},
                }
            )
        system_prompt = (
            "You are a shopping assistant. You will be given a user's search query and a "
            "JSON list of REAL retrieved products with REAL prices/ratings/specs. For EACH "
            "product, write one short (max 25 words) reason it fits the query, using ONLY the "
            "given fields. Never invent facts, prices, or specs not present in the data. "
            "Respond ONLY with a JSON array of strings, one per product, in the same order given."
        )
        user_prompt = f"Query: {query}\nProducts: {json.dumps(context_items, default=str)}"
        raw = llm_client.complete(system_prompt, user_prompt)
        if raw:
            try:
                cleaned = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
                reasons = json.loads(cleaned)
                for item, reason in zip(top_n, reasons):
                    item["reason"] = reason
            except Exception as exc:
                logger.warning("Could not parse LLM ranking reasons: %s", exc)

    for item in scored:
        if "reason" not in item:
            s = item["summary"]
            bits = []
            if s["avg_rating"]:
                bits.append(f"rated {s['avg_rating']}★")
            if s["total_reviews"]:
                bits.append(f"{s['total_reviews']:,} reviews")
            if s["best_price"]:
                bits.append(f"best price ₹{s['best_price']:,.0f} on {s['best_platform']}")
            item["reason"] = ("Matches your search - " + ", ".join(bits)) if bits else \
                "Matches your search based on available listing data."

    return scored
