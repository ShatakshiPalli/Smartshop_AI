"""
RAG shopping assistant. Retrieves grounding context from the database
(product specs, offers, reviews) - using semantic similarity when a
product isn't explicitly specified - and asks the LLM to answer using
ONLY that retrieved context. If no LLM is configured, returns a graceful
message instead of a hallucinated answer.
"""
import json
import logging
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models import Product, Review
from app.services.embeddings import semantic_rerank
from app.services.llm import llm_client
from app.services.sentiment import analyze_reviews

logger = logging.getLogger("smartshop.assistant")

SYSTEM_PROMPT = (
    "You are SmartShop AI's shopping assistant. Answer the user's question using ONLY the "
    "retrieved product context provided below (titles, specs, prices, ratings, reviews). "
    "If the answer isn't supported by the context, say you don't have enough retrieved data "
    "to answer confidently instead of guessing. Never invent prices, specs, or review content. "
    "Keep answers concise and practical."
)


def build_fallback_answer(question: str, context: str, sources: List[str]) -> str:
    """Generate a natural answer from database context when LLM isn't available."""
    q = (question or "").lower()
    lines = [line.strip() for line in context.splitlines() if line.strip()]
    product_names = []
    for line in lines:
        if line.startswith("PRODUCT:"):
            name = line.replace("PRODUCT:", "", 1).split(" (brand:", 1)[0].strip()
            if name:
                product_names.append(name)

    if not product_names:
        product_names = sources or ["the selected product"]

    best_name = product_names[0]
    offers_line = next((line for line in lines if line.startswith("Offers:")), "")
    ratings_line = next((line for line in lines if line.startswith("Ratings:")), "")
    sentiment_line = next((line for line in lines if line.startswith("Sentiment:")), "")
    specs_line = next((line for line in lines if line.startswith("Specs:")), "")

    offers_text = offers_line.replace("Offers: ", "").strip() if offers_line else "Price info not available."
    ratings_text = ratings_line.replace("Ratings: ", "").strip() if ratings_line else "No ratings yet."
    sentiment_text = sentiment_line.replace("Sentiment: ", "").strip() if sentiment_line else "Sentiment data not available."
    specs_text = specs_line.replace("Specs: ", "").strip() if specs_line else "Specs not listed."

    if any(term in q for term in ["price", "cheap", "budget", "cost", "affordable", "how much"]):
        return (
            f"**{best_name}**\n\n"
            f"💰 **Pricing:** {offers_text}\n\n"
            f"📋 **Specs:** {specs_text}\n\n"
            f"Based on current offers, this is priced as shown above. Check individual retailers for the latest deals."
        )

    if any(term in q for term in ["rating", "reviews", "good", "bad", "worth", "quality", "reliable", "sentiment", "noise", "cancell"]):
        return (
            f"**{best_name}**\n\n"
            f"⭐ **Ratings:** {ratings_text}\n\n"
            f"💬 **Sentiment Analysis:** {sentiment_text}\n\n"
            f"Based on customer feedback and analysis, here's what we found."
        )

    if any(term in q for term in ["best", "recommend", "which", "choose", "compare", "better"]):
        return (
            f"**{best_name}**\n\n"
            f"🎯 **Key Specs:** {specs_text}\n\n"
            f"⭐ **User Rating:** {ratings_text}\n\n"
            f"💬 **Customer Sentiment:** {sentiment_text}\n\n"
            f"This looks like a solid option based on the specs and customer sentiment."
        )

    return (
        f"**{best_name}**\n\n"
        f"📋 **Specs:** {specs_text}\n\n"
        f"💰 **Offers:** {offers_text}\n\n"
        f"⭐ **Ratings:** {ratings_text}\n\n"
        f"💬 **Customer Sentiment:** {sentiment_text}\n\n"
        f"What specifically would you like to know about this product?"
    )


def _build_context(products: List[Product], sentiment_by_product: dict) -> str:
    blocks = []
    for p in products:
        offers_text = "; ".join(
            f"{o.platform}: ₹{o.price:,.0f}" if o.price else f"{o.platform}: price unavailable"
            for o in p.offers
        )
        ratings_text = "; ".join(
            f"{o.platform} rating {o.rating}★ ({o.review_count or 0} reviews)"
            for o in p.offers
            if o.rating is not None
        )
        spec_text = ", ".join(f"{k}: {v}" for k, v in (p.specifications or {}).items())
        
        # Add sentiment analysis instead of raw reviews
        sentiment = sentiment_by_product.get(p.id, {})
        sentiment_text = ""
        if sentiment:
            pos = sentiment.get("positive_pct", 0)
            neg = sentiment.get("negative_pct", 0)
            summary = sentiment.get("summary_text", "")
            sentiment_text = f"Sentiment: {pos}% positive, {neg}% negative. {summary}"

        blocks.append(
            f"PRODUCT: {p.canonical_title} (brand: {p.brand})\n"
            f"Offers: {offers_text}\nRatings: {ratings_text}\nSpecs: {spec_text}"
            + (f"\nSentiment: {sentiment_text}" if sentiment_text else "")
        )
    return "\n\n".join(blocks)


def answer_question(
    db: Session, question: str, product_id: Optional[str] = None, top_k: int = 5
) -> dict:
    if product_id:
        candidates = db.query(Product).filter(Product.id == product_id).all()
    else:
        candidates = db.query(Product).limit(200).all()
        if candidates:
            scores = semantic_rerank(candidates, question)
            candidates.sort(key=lambda p: scores.get(p.id, 0.0), reverse=True)
        candidates = candidates[:top_k]

    if not candidates:
        return {
            "answer": "I don't have any retrieved product data yet to answer that. Try searching for a product first.",
            "sources": [],
        }

    sentiment_by_product = {}
    for p in candidates:
        reviews = db.query(Review).filter(Review.product_id == p.id).all()
        product_context = f"{p.canonical_title} ({p.brand}) - {p.category or 'general'}"
        total_reviews = getattr(p, 'review_count', None) or len(reviews)
        sentiment = analyze_reviews(reviews, product_context=product_context, total_review_count=total_reviews) if reviews else {}
        sentiment_by_product[p.id] = sentiment

    context = _build_context(candidates, sentiment_by_product)

    sources = [p.canonical_title for p in candidates]

    if not llm_client.available:
        return {
            "answer": build_fallback_answer(question, context, sources),
            "sources": sources,
        }

    user_prompt = f"Retrieved context:\n{context}\n\nUser question: {question}"
    answer = llm_client.complete(SYSTEM_PROMPT, user_prompt)
    if not answer:
        answer = build_fallback_answer(question, context, sources)

    return {"answer": answer, "sources": sources}
