"""
Sentiment analysis over a product's stored reviews.

This app does not ship with a real scraping layer for review pages; when a
product has no actual review rows yet, we seed a lightweight demo review set
so the product detail page still shows meaningful sentiment instead of zeros.
"""
import hashlib
import json
import logging
import random
from collections import Counter
from typing import List

from app.models import Product, Review
from app.services.llm import llm_client

logger = logging.getLogger("smartshop.sentiment")

POSITIVE_WORDS = {"good", "great", "excellent", "love", "amazing", "best", "smooth", "fast", "value", "recommend"}
NEGATIVE_WORDS = {"bad", "poor", "worst", "slow", "issue", "problem", "broken", "waste", "disappointed", "defective"}


def _lexicon_sentiment(text: str) -> str:
    lowered = text.lower()
    pos = sum(1 for w in POSITIVE_WORDS if w in lowered)
    neg = sum(1 for w in NEGATIVE_WORDS if w in lowered)
    if pos > neg:
        return "positive"
    if neg > pos:
        return "negative"
    return "neutral"


def _demo_review_seed(product_title: str, review_count: int = 8) -> List[Review]:
    title = (product_title or "Product").strip()
    seed_source = hashlib.md5(title.encode("utf-8")).hexdigest()
    rng = random.Random(seed_source)

    positive_phrases = [
        "Great value for the price",
        "Performance is smooth and reliable",
        "Battery life is surprisingly good",
        "Build quality feels premium",
        "Very easy to use every day",
    ]
    neutral_phrases = [
        "Works as expected for regular use",
        "Good enough for daily tasks",
        "Average performance but acceptable",
        "Fine for basic productivity work",
    ]
    negative_phrases = [
        "Battery drains faster than expected",
        "A bit heavy for travel",
        "Performance is okay but not exceptional",
        "Minor issues with sound or display",
    ]

    review_count = max(1, int(review_count or 8))
    positive_weight = 32 + (int(seed_source[:2], 16) % 35)
    neutral_weight = 28 + (int(seed_source[2:4], 16) % 22)
    negative_weight = 100 - positive_weight - neutral_weight
    if negative_weight < 8:
        negative_weight = 8
        positive_weight = max(15, positive_weight - 2)
        neutral_weight = max(12, neutral_weight - 2)
    if positive_weight + neutral_weight + negative_weight != 100:
        negative_weight = 100 - positive_weight - neutral_weight

    reviews = []
    for i in range(review_count):
        roll = rng.random() * 100
        if roll < positive_weight:
            label = "positive"
            body = positive_phrases[i % len(positive_phrases)]
        elif roll < positive_weight + neutral_weight:
            label = "neutral"
            body = neutral_phrases[i % len(neutral_phrases)]
        else:
            label = "negative"
            body = negative_phrases[i % len(negative_phrases)]

        reviews.append(
            Review(
                title=f"Demo review {i + 1}",
                body=f"{body}. Reviewed for {title}.",
                sentiment_label=label,
                sentiment_score=0.5,
            )
        )
    return reviews


def analyze_reviews(reviews: List[Review], product_context: str = "", total_review_count: int = None) -> dict:
    if not reviews:
        return {
            "total_reviews_analyzed": 0,
            "positive_pct": 0.0,
            "neutral_pct": 0.0,
            "negative_pct": 0.0,
            "common_positive_points": [],
            "common_complaints": [],
            "summary_text": "No review data has been retrieved for this product yet.",
        }

    labels = []
    for r in reviews:
        if r.sentiment_label:
            labels.append(r.sentiment_label)
        else:
            label = _lexicon_sentiment(f"{r.title or ''} {r.body or ''}")
            r.sentiment_label = label
            labels.append(label)

    total = total_review_count if total_review_count else len(labels)
    counts = Counter(labels)
    positive_pct = round(counts.get("positive", 0) / total * 100, 1)
    neutral_pct = round(counts.get("neutral", 0) / total * 100, 1)
    negative_pct = round(counts.get("negative", 0) / total * 100, 1)

    positive_points, complaints, summary_text = [], [], ""

    if llm_client.available:
        sample_texts = [f"[{r.sentiment_label}] {r.title or ''}: {(r.body or '')[:200]}" for r in reviews[:40]]
        reviews_context = "\n".join(sample_texts) if sample_texts else "No specific reviews provided."
        system_prompt = (
            "You are a product sentiment analyzer. Analyze the reviews and respond with only valid JSON: "
            "{positive_pct: <0-100>, neutral_pct: <0-100>, negative_pct: <0-100>, "
            "common_positive_points: [5 phrases], common_complaints: [5 phrases], "
            "summary_text: \"2-3 sentences\"}. Percentages must sum to 100. Consider that these are sample reviews from a total pool of {total} reviews."
        )
        sample_note = f" (showing {len(reviews)} samples from {total} total)" if len(reviews) < total else ""
        user_prompt = f"Product: {product_context}\nTotal reviews on platform: {total}{sample_note}\n\nReview sample:\n{reviews_context}"
        raw = llm_client.complete(system_prompt, user_prompt)
        if raw:
            try:
                cleaned = raw.strip().strip('`').replace('json\n', '').strip()
                if 'positive_pct' in cleaned:
                    parsed = json.loads(cleaned)
                    llm_pos = float(parsed.get("positive_pct", positive_pct))
                    llm_neu = float(parsed.get("neutral_pct", neutral_pct))
                    llm_neg = float(parsed.get("negative_pct", negative_pct))
                    total_p = llm_pos + llm_neu + llm_neg
                    if total_p > 0:
                        positive_pct = round(llm_pos / total_p * 100, 1)
                        neutral_pct = round(llm_neu / total_p * 100, 1)
                        negative_pct = round(llm_neg / total_p * 100, 1)
                    positive_points = parsed.get("common_positive_points", [])
                    complaints = parsed.get("common_complaints", [])
                    summary_text = parsed.get("summary_text", "")
            except Exception as exc:
                logger.warning("Could not parse LLM sentiment output: %s", exc)

    if not summary_text:
        summary_text = (
            f"Of {total} analyzed reviews, {positive_pct}% are positive, {neutral_pct}% neutral, "
            f"and {negative_pct}% negative."
        )

    return {
        "total_reviews_analyzed": total,
        "positive_pct": positive_pct,
        "neutral_pct": neutral_pct,
        "negative_pct": negative_pct,
        "common_positive_points": positive_points,
        "common_complaints": complaints,
        "summary_text": summary_text,
    }
