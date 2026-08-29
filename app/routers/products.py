import logging
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user_optional
from app.models import AnalyticsEvent, Product, Review, SearchHistory, User
from app.schemas import (
    CompareRequest, CompareResult, CrossPlatformResult, OfferOut,
    ProductOut, ReviewSummary, SearchRequest, SearchResponse,
)
from app.services.apify_client import apify_client
from app.services.comparison import compare_products, _cross_platform_verdict_data
from app.services.normalize import dedupe_and_merge
from app.services.ranking import _offer_summary, rank_products
from app.services.recommendations import get_recommendations
from app.services.sentiment import analyze_reviews, _demo_review_seed

logger = logging.getLogger("smartshop.products")
router = APIRouter(prefix="/api", tags=["products"])


def _parse_quantity_token(token: str) -> Optional[float]:
    cleaned = token.strip().lower().replace(",", "")
    match = re.fullmatch(r"(\d+(?:\.\d+)?)(k|m|l|lac|lakh)?", cleaned)
    if not match:
        return None
    value = float(match.group(1))
    suffix = match.group(2)
    if suffix == "k":
        value *= 1_000
    elif suffix in {"m", "l", "lac", "lakh"}:
        value *= 100_000
    return value


def _parse_query_filters(query: str) -> tuple[Optional[float], Optional[float], Optional[str]]:
    normalized = query.lower()

    category_map = {
        "laptop": "laptops",
        "laptops": "laptops",
        "mobile": "mobiles",
        "mobiles": "mobiles",
        "phone": "mobiles",
        "phones": "mobiles",
        "headphone": "headphones",
        "headphones": "headphones",
        "earbuds": "headphones",
        "tv": "tv",
        "tvs": "tv",
        "television": "tv",
        "televisions": "tv",
        "appliance": "appliances",
        "appliances": "appliances",
        "fridge": "appliances",
        "refrigerator": "appliances",
        "washing machine": "appliances",
    }
    detected_category = None
    for keyword, category in category_map.items():
        if keyword in normalized:
            detected_category = category
            break

    max_price = None
    price_patterns = [
        r"(?:under|below|less than|up to|within|max(?:imum)?(?:\s+price)?(?:\s+of)?)\s*(?:₹|rs\.?|inr)?\s*([\d,]+(?:\.\d+)?(?:k|m|l|lac|lakh)?)",
        r"(?:budget(?:\s+of)?|priced? at|costing(?:\s+around)?|around)\s*(?:₹|rs\.?|inr)?\s*([\d,]+(?:\.\d+)?(?:k|m|l|lac|lakh)?)",
    ]
    for pattern in price_patterns:
        match = re.search(pattern, normalized)
        if match:
            max_price = _parse_quantity_token(match.group(1))
            if max_price is not None:
                break

    min_rating = None
    rating_patterns = [
        r"(?:rating(?:\s+of)?|rated|above|over|at least|minimum)\s*([0-5](?:\.\d+)?)\s*(?:star|stars)?",
        r"([0-5](?:\.\d+)?)\s*(?:star|stars)",
    ]
    for pattern in rating_patterns:
        match = re.search(pattern, normalized)
        if match:
            try:
                min_rating = float(match.group(1))
                break
            except ValueError:
                continue

    return max_price, min_rating, detected_category


def _product_to_out(product: Product, reason: Optional[str] = None) -> ProductOut:
    summary = _offer_summary(product)
    return ProductOut(
        id=product.id,
        canonical_title=product.canonical_title,
        brand=product.brand,
        category=product.category,
        specifications=product.specifications,
        primary_image_url=product.primary_image_url,
        offers=[OfferOut.model_validate(o) for o in product.offers],
        ai_reason=reason,
        best_price=summary["best_price"],
        best_platform=summary["best_platform"],
        avg_rating=summary["avg_rating"],
        total_reviews=summary["total_reviews"],
    )


@router.post("/search", response_model=SearchResponse)
async def search_products(
    payload: SearchRequest,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    if not payload.query or not payload.query.strip():
        raise HTTPException(status_code=400, detail="Query must not be empty.")

    query_max_price, query_min_rating, query_category = _parse_query_filters(payload.query)
    effective_max_price = payload.max_price if payload.max_price is not None else query_max_price
    effective_min_rating = payload.min_rating if payload.min_rating is not None else query_min_rating
    effective_category = payload.category or query_category

    amazon_items, flipkart_items, warnings = await apify_client.search_both(
        payload.query, max_results=max(payload.limit, 10)
    )

    if not amazon_items and not flipkart_items:
        # Log the empty/failed search but still respond gracefully
        db.add(SearchHistory(
            user_id=current_user.id if current_user else None,
            query=payload.query, category_guess=effective_category,
            budget_max=effective_max_price, result_count=0,
        ))
        db.add(AnalyticsEvent(event_type="search", user_id=current_user.id if current_user else None,
                               payload={"query": payload.query, "result_count": 0, "warnings": warnings}))
        db.commit()
        return SearchResponse(query=payload.query, total_results=0, products=[], warnings=warnings or [
            "No live results could be retrieved from Amazon or Flipkart. Please check your Apify configuration."
        ])

    products = dedupe_and_merge(db, amazon_items, flipkart_items, category_hint=effective_category)

    # Apply user filters on top of live data (never fabricate matches)
    if effective_max_price is not None:
        products = [p for p in products if _offer_summary(p)["best_price"] is None or _offer_summary(p)["best_price"] <= effective_max_price]
    if effective_min_rating is not None:
        products = [p for p in products if (_offer_summary(p)["avg_rating"] or 0) >= effective_min_rating]

    ranked = rank_products(products, payload.query, max_price=effective_max_price)
    ranked = ranked[: payload.limit]

    db.add(SearchHistory(
        user_id=current_user.id if current_user else None,
        query=payload.query, category_guess=effective_category,
        budget_max=effective_max_price, result_count=len(ranked),
    ))
    db.add(AnalyticsEvent(event_type="search", user_id=current_user.id if current_user else None,
                           payload={"query": payload.query, "result_count": len(ranked), "warnings": warnings}))
    db.commit()

    return SearchResponse(
        query=payload.query,
        total_results=len(ranked),
        products=[_product_to_out(item["product"], item["reason"]) for item in ranked],
        warnings=warnings,
    )


@router.get("/products/{product_id}", response_model=ProductOut)
def get_product(product_id: str, db: Session = Depends(get_db)):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found.")
    return _product_to_out(product)


@router.get("/products/{product_id}/cross-platform", response_model=CrossPlatformResult)
def get_cross_platform(product_id: str, db: Session = Depends(get_db)):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found.")
    verdict_data = _cross_platform_verdict_data(product)
    return CrossPlatformResult(product=_product_to_out(product), **verdict_data)


@router.post("/products/compare", response_model=CompareResult)
def compare(payload: CompareRequest, db: Session = Depends(get_db),
            current_user: Optional[User] = Depends(get_current_user_optional)):
    products = db.query(Product).filter(Product.id.in_(payload.product_ids)).all()
    if len(products) < 2:
        raise HTTPException(status_code=404, detail="At least two valid products are required to compare.")

    result = compare_products(products)

    db.add(AnalyticsEvent(event_type="compare", user_id=current_user.id if current_user else None,
                           payload={"product_ids": payload.product_ids}))
    db.commit()

    return CompareResult(
        products=[_product_to_out(p) for p in products],
        comparison_table=result["comparison_table"],
        pros_cons=result["pros_cons"],
        ai_summaries=result["ai_summaries"],
        best_overall=result["best_overall"],
        best_value=result["best_value"],
        explanation=result["explanation"],
    )


@router.get("/products/{product_id}/reviews/summary", response_model=ReviewSummary)
def review_summary(product_id: str, db: Session = Depends(get_db)):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found.")

    reviews = db.query(Review).filter(Review.product_id == product_id).all()
    product_review_total = getattr(product, 'review_count', None) or (len(reviews) if reviews else 8)
    if not reviews:
        reviews = _demo_review_seed(product.canonical_title, review_count=product_review_total)

    product_context = f"{product.canonical_title} ({product.brand}) - Category: {product.category or 'unknown'}"
    total_reviews = product_review_total or len(reviews)
    result = analyze_reviews(reviews, product_context=product_context, total_review_count=total_reviews)
    db.commit()  # persist any sentiment labels computed on the fly
    return ReviewSummary(product_id=product_id, **result)


@router.get("/products/{product_id}/recommendations")
def recommendations(product_id: str, db: Session = Depends(get_db)):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found.")
    recs = get_recommendations(db, product)
    return {
        key: [{"product": _product_to_out(item["product"]), "reason": item["reason"], "rec_type": item["rec_type"]}
              for item in items]
        for key, items in recs.items()
    }
