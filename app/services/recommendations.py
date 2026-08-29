"""
Generates similar / better-alternative / budget / premium recommendations
for a given product, using semantic similarity plus real price/rating data
already stored in the DB (no invented products).
"""
from typing import Dict, List, Optional

from sqlalchemy import or_

from sqlalchemy.orm import Session

from app.models import Product
from app.services.embeddings import semantic_rerank
from app.services.ranking import _offer_summary

ASSOCIATION_RULES = {
    "laptop": {
        "aliases": ["laptop", "laptops"],
        "terms": ["keyboard", "mouse", "laptop bag", "laptop sleeve", "mouse pad", "cooling pad", "webcam"],
        "labels": {
            "keyboard": "Common laptop add-on for work and study.",
            "mouse": "Useful for better control and productivity.",
            "laptop bag": "Popular carry accessory for laptops.",
            "laptop sleeve": "Helps protect the laptop during travel.",
            "mouse pad": "Improves comfort and cursor precision.",
            "cooling pad": "Helpful for keeping laptops cooler under load.",
            "webcam": "Often paired with laptops for meetings and classes.",
        },
    },
    "mobile": {
        "aliases": ["mobile", "mobiles", "phone", "phones", "smartphone", "smartphones"],
        "terms": ["case", "cover", "screen protector", "charger", "power bank", "earbuds"],
        "labels": {
            "case": "Common protection accessory for phones.",
            "cover": "Protects the phone from scratches and drops.",
            "screen protector": "Frequently bought to protect the display.",
            "charger": "Useful spare or fast-charging accessory.",
            "power bank": "Helpful for charging on the go.",
            "earbuds": "Frequently paired with mobile phones.",
        },
    },
    "headphone": {
        "aliases": ["headphone", "headphones", "earbuds", "earphone", "earphones"],
        "terms": ["case", "carry case", "adapter", "usb c", "audio cable"],
        "labels": {
            "case": "Good for carrying and protecting headphones.",
            "carry case": "Popular travel accessory for headphones.",
            "adapter": "Useful for compatibility with other devices.",
            "usb c": "Helpful if the headset needs charging accessories.",
            "audio cable": "Good backup accessory for wired use.",
        },
    },
    "tv": {
        "aliases": ["tv", "television", "smart tv"],
        "terms": ["wall mount", "soundbar", "hdmi cable", "tv stand"],
        "labels": {
            "wall mount": "Commonly paired for TV installation.",
            "soundbar": "Natural companion for better audio.",
            "hdmi cable": "Useful for connecting other devices.",
            "tv stand": "Helpful if you do not want a wall mount.",
        },
    },
}


def _association_rule_terms(product: Product) -> Optional[Dict[str, object]]:
    title = (product.canonical_title or "").lower()
    category = (product.category or "").lower()
    for key, rule in ASSOCIATION_RULES.items():
        aliases = rule.get("aliases", [key])
        if any(alias in title or alias in category for alias in aliases):
            return rule
    return None


def _association_recommendations(db: Session, product: Product, limit: int = 4) -> List[dict]:
    rule = _association_rule_terms(product)
    if not rule:
        return []

    terms = rule["terms"]
    labels = rule["labels"]
    candidates = db.query(Product).filter(Product.id != product.id).filter(
        or_(*[Product.canonical_title.ilike(f"%{term}%") | Product.category.ilike(f"%{term}%") for term in terms])
    ).limit(200).all()

    if not candidates:
        return []

    ranked = []
    for candidate in candidates:
        lowered = candidate.canonical_title.lower()
        matched_term = next((term for term in terms if term in lowered or (candidate.category or "").lower().find(term) >= 0), None)
        summary = _offer_summary(candidate)
        title = candidate.canonical_title.lower()
        bonus = 0.0
        if matched_term and matched_term in title:
            bonus += 0.4
        if matched_term and (candidate.category or "").lower().find(matched_term) >= 0:
            bonus += 0.2
        ranked.append({
            "product": candidate,
            "score": (summary["avg_rating"] or 0) + bonus,
            "matched_term": matched_term,
        })

    ranked.sort(key=lambda item: (item["score"], item["product"].canonical_title), reverse=True)

    results = []
    for item in ranked[:limit]:
        matched_term = item["matched_term"] or "bundle item"
        reason = labels.get(matched_term, f"Frequently bought together with {product.canonical_title}.")
        results.append({"product": item["product"], "reason": reason, "rec_type": "association"})
    return results


def get_recommendations(db: Session, product: Product, limit: int = 4) -> Dict[str, List[dict]]:
    pool_query = db.query(Product).filter(Product.id != product.id)
    if product.category:
        pool_query = pool_query.filter(Product.category == product.category)
    pool = pool_query.limit(200).all()

    if not pool:
        return {
            "associated_bundles": _association_recommendations(db, product, limit),
            "similar": [],
            "better_alternatives": [],
            "budget_alternatives": [],
            "premium_alternatives": [],
        }

    sim_scores = semantic_rerank(pool, product.canonical_title)
    base_summary = _offer_summary(product)
    base_price = base_summary["best_price"]
    base_rating = base_summary["avg_rating"] or 0

    scored_pool = []
    for p in pool:
        summary = _offer_summary(p)
        scored_pool.append({"product": p, "summary": summary, "similarity": sim_scores.get(p.id, 0.0)})

    similar = sorted(scored_pool, key=lambda x: x["similarity"], reverse=True)[:limit]

    better = [
        x for x in scored_pool
        if (x["summary"]["avg_rating"] or 0) > base_rating
        and (base_price is None or (x["summary"]["best_price"] or 0) <= (base_price * 1.15 if base_price else 0))
    ]
    better = sorted(better, key=lambda x: (x["summary"]["avg_rating"] or 0), reverse=True)[:limit]

    budget = []
    premium = []
    if base_price:
        budget = [x for x in scored_pool if x["summary"]["best_price"] and x["summary"]["best_price"] < base_price * 0.85]
        budget = sorted(budget, key=lambda x: x["summary"]["best_price"])[:limit]

        premium = [x for x in scored_pool if x["summary"]["best_price"] and x["summary"]["best_price"] > base_price * 1.15]
        premium = sorted(premium, key=lambda x: (x["summary"]["avg_rating"] or 0), reverse=True)[:limit]

    def _fmt(items, reason_fn, rec_type):
        return [
            {"product": x["product"], "reason": reason_fn(x), "rec_type": rec_type}
            for x in items
        ]

    def _fmt_constant(items, reason_text, rec_type):
        return [
            {"product": x["product"], "reason": reason_text, "rec_type": rec_type}
            for x in items
        ]

    def _fmt_similar(items):
        if not items:
            return []
        best_similarity = max((x["similarity"] for x in items), default=0) or 0
        payload = []
        for x in items:
            similarity = x["similarity"] or 0
            if similarity >= max(best_similarity - 0.05, 0.15):
                reason = "Closest match based on title, features, and category."
            elif similarity >= 0.35:
                reason = "Very similar option with comparable positioning."
            else:
                reason = "A related alternative worth checking against your current pick."
            payload.append({"product": x["product"], "reason": reason, "rec_type": "similar"})
        return payload

    return {
        "associated_bundles": _association_recommendations(db, product, limit),
        "similar": _fmt_similar(similar),
        "better_alternatives": _fmt(
            better,
            lambda x: f"Rated {x['summary']['avg_rating']}★ vs {base_rating}★, at a comparable price.",
            "better_alternative",
        ),
        "budget_alternatives": _fmt(
            budget,
            lambda x: f"₹{x['summary']['best_price']:,.0f} - cheaper than your current selection.",
            "budget",
        ),
        "premium_alternatives": _fmt(
            premium,
            lambda x: f"₹{x['summary']['best_price']:,.0f} - a higher-end option with strong ratings.",
            "premium",
        ),
    }
