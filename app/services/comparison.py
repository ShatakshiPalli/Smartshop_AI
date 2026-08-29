"""
Two kinds of comparison:
1. cross_platform_verdict: same product, Amazon vs Flipkart offers.
2. compare_products: multiple different products, side by side.
Both only ever reason over data actually stored on the Product/Offer rows -
never fabricated numbers.
"""
import json
import logging
from typing import Dict, List

from app.models import Product, Review
from app.services.llm import llm_client
from app.services.sentiment import analyze_reviews

logger = logging.getLogger("smartshop.comparison")


def cross_platform_verdict(product: Product) -> str:
    verdict = _cross_platform_verdict_data(product)
    return verdict["ai_verdict"]


def _cross_platform_verdict_data(product: Product) -> Dict[str, str]:
    offers = [o for o in product.offers if o.price is not None]
    if len(offers) < 2:
        message = "This product is currently only available with pricing data on one platform, so a cross-platform comparison isn't possible yet."
        return {
            "ai_verdict": message,
            "best_platform": None,
            "amazon_explanation": message,
            "flipkart_explanation": message,
        }

    cheapest = min(offers, key=lambda o: o.price)
    best_rated = max((o for o in offers if o.rating is not None), key=lambda o: o.rating, default=None)
    most_reviewed = max((o for o in offers if o.review_count is not None), key=lambda o: o.review_count, default=None)

    best_platform = cheapest.platform.capitalize()
    if best_rated and best_rated.platform != cheapest.platform and best_rated.rating >= (cheapest.rating or 0):
        best_platform = best_rated.platform.capitalize()

    if llm_client.available:
        # Get sentiment analysis for each platform's reviews
        platform_data = []
        product_context = f"{product.canonical_title} ({product.brand})"
        for o in offers:
            reviews_for_offer = product.reviews if product.reviews else []
            total_for_offer = getattr(o, 'review_count', None) or len(reviews_for_offer)
            sentiment = analyze_reviews(reviews_for_offer, product_context=product_context, total_review_count=total_for_offer) if reviews_for_offer else {
                "positive_pct": 0, "neutral_pct": 0, "negative_pct": 0,
                "common_positive_points": [], "common_complaints": []
            }
            platform_data.append({
                "platform": o.platform,
                "price": o.price,
                "rating": o.rating,
                "review_count": o.review_count,
                "sentiment_positive_pct": sentiment.get("positive_pct", 0),
                "sentiment_negative_pct": sentiment.get("negative_pct", 0),
                "positive_points": sentiment.get("common_positive_points", [])[:2],
                "complaints": sentiment.get("common_complaints", [])[:2],
            })

        system_prompt = (
            "You compare the SAME product's offers across Amazon and Flipkart using ONLY the "
            "given real price/rating/review data AND sentiment analysis. Write 1-2 sentences naming which "
            "platform is the better deal and why, referencing the actual numbers and sentiment insights. "
            "If sentiment differs significantly between platforms, mention that. Never invent data not given."
        )
        raw = llm_client.complete(system_prompt, json.dumps(platform_data))
        if raw:
            text = raw.strip()
            return {
                "ai_verdict": text,
                "best_platform": best_platform,
                "amazon_explanation": _build_platform_explanation(product, "amazon"),
                "flipkart_explanation": _build_platform_explanation(product, "flipkart"),
            }

    # Deterministic fallback
    parts = [f"{cheapest.platform.capitalize()} is cheaper at ₹{cheapest.price:,.0f}."]
    if best_rated and best_rated.platform != cheapest.platform:
        parts.append(f"{best_rated.platform.capitalize()} has a higher rating ({best_rated.rating}★).")
    if most_reviewed:
        parts.append(f"{most_reviewed.platform.capitalize()} has the most reviews ({most_reviewed.review_count:,}).")
    verdict = " ".join(parts)
    return {
        "ai_verdict": verdict,
        "best_platform": best_platform,
        "amazon_explanation": _build_platform_explanation(product, "amazon"),
        "flipkart_explanation": _build_platform_explanation(product, "flipkart"),
    }


def compare_products(products: List[Product]) -> Dict:
    table = {}
    for p in products:
        prices = [o.price for o in p.offers if o.price is not None]
        ratings = [o.rating for o in p.offers if o.rating is not None]
        reviews = [o.review_count for o in p.offers if o.review_count is not None]
        table[p.id] = {
            "title": p.canonical_title,
            "brand": p.brand,
            "best_price": min(prices) if prices else None,
            "avg_rating": round(sum(ratings) / len(ratings), 2) if ratings else None,
            "total_reviews": sum(reviews) if reviews else 0,
            "platforms": [o.platform for o in p.offers],
            "specifications": p.specifications or {},
        }

    valid_price = {pid: v for pid, v in table.items() if v["best_price"]}
    valid_rating = {pid: v for pid, v in table.items() if v["avg_rating"]}

    best_overall = max(valid_rating, key=lambda pid: (valid_rating[pid]["avg_rating"], valid_rating[pid]["total_reviews"]), default=None)
    best_value = min(valid_price, key=lambda pid: valid_price[pid]["best_price"], default=None)

    pros_cons = {}
    for pid, row in table.items():
        pros, cons = [], []
        if row["avg_rating"] and row["avg_rating"] >= 4.2:
            pros.append(f"Highly rated ({row['avg_rating']}★)")
        elif row["avg_rating"] and row["avg_rating"] < 3.8:
            cons.append(f"Lower rating ({row['avg_rating']}★)")
        if row["total_reviews"] and row["total_reviews"] > 1000:
            pros.append(f"Well reviewed ({row['total_reviews']:,} reviews)")
        elif not row["total_reviews"]:
            cons.append("Limited review data available")
        if len(row["platforms"]) > 1:
            pros.append("Available on multiple platforms for price comparison")
        if not row["best_price"]:
            cons.append("Price currently unavailable")
        pros_cons[pid] = {"pros": pros, "cons": cons}

    ai_summaries = {}
    for product in products:
        offers_with_prices = [o for o in product.offers if o.price is not None]
        if len(offers_with_prices) >= 2:
            ai_summaries[product.id] = _cross_platform_verdict_data(product)

    explanation = ""
    if llm_client.available:
        system_prompt = (
            "Given a JSON comparison table of real products (price/rating/reviews/specs), "
            "write a short 2-3 sentence explanation of the trade-offs between them, using ONLY "
            "the given data. Do not invent any facts."
        )
        raw = llm_client.complete(system_prompt, json.dumps(table, default=str))
        if raw:
            explanation = raw.strip()
    if not explanation:
        bo = table.get(best_overall, {}).get("title") if best_overall else None
        bv = table.get(best_value, {}).get("title") if best_value else None
        explanation = (
            f"Based on retrieved data, {bo or 'the top-rated option'} has the strongest "
            f"rating/review profile, while {bv or 'the cheapest option'} offers the lowest price."
        )

    return {
        "comparison_table": table,
        "pros_cons": pros_cons,
        "ai_summaries": ai_summaries,
        "best_overall": best_overall,
        "best_value": best_value,
        "explanation": explanation,
    }


def _build_platform_explanation(product: Product, preferred_platform: str) -> str:
    offers = [o for o in product.offers if o.price is not None]
    preferred = next((o for o in offers if o.platform == preferred_platform), None)
    if not preferred:
        return ""

    other = next((o for o in offers if o.platform != preferred_platform), None)
    if not other:
        return f"{preferred_platform.capitalize()} currently has the only pricing data available for this product."

    cheapest = min(offers, key=lambda o: o.price)
    best_rated = max((o for o in offers if o.rating is not None), key=lambda o: o.rating, default=None)
    most_reviewed = max((o for o in offers if o.review_count is not None), key=lambda o: o.review_count, default=None)

    opening = f"{preferred_platform.capitalize()} is {'cheaper' if preferred is cheapest else 'a stronger value'} for this listing"
    if preferred is cheapest:
        opening += f" at ₹{preferred.price:,.0f}."
    else:
        opening += "."

    support_bits = []
    if best_rated and best_rated.platform == preferred_platform:
        support_bits.append(f"It also carries the better rating at {best_rated.rating}★.")
    if most_reviewed and most_reviewed.platform == preferred_platform:
        support_bits.append(f"It has the larger review base with {most_reviewed.review_count:,} reviews.")
    if not support_bits:
        support_bits.append("The other platform remains competitive, so the final choice depends on whether you value price, rating, or review volume more.")

    return f"{opening} {' '.join(support_bits)}"
