from collections import Counter
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AnalyticsEvent, Product, SearchHistory
from app.schemas import AnalyticsSummary, ClickTrackRequest

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("/summary", response_model=AnalyticsSummary)
def summary(db: Session = Depends(get_db)):
    total_searches = int(db.execute(text("SELECT COUNT(*) FROM search_history")).scalar() or 0)

    query_rows = db.query(SearchHistory.query).all()
    query_counts = Counter(q for (q,) in query_rows)
    top_queries = [{"query": q, "count": c} for q, c in query_counts.most_common(10)]

    category_rows = db.query(Product.category).filter(Product.category.isnot(None)).all()
    category_counts = Counter(c for (c,) in category_rows)
    top_categories = [{"category": c, "count": n} for c, n in category_counts.most_common(10)]

    brand_rows = db.query(Product.brand).filter(Product.brand.isnot(None)).all()
    brand_counts = Counter(b for (b,) in brand_rows)
    top_brands = [{"brand": b, "count": n} for b, n in brand_counts.most_common(10)]

    since = datetime.now(timezone.utc) - timedelta(days=14)
    recent = db.query(SearchHistory.created_at).filter(SearchHistory.created_at >= since).all()
    day_counts = Counter(dt.date().isoformat() for (dt,) in recent)

    day_labels = []
    cursor = datetime.now(timezone.utc).date()
    for offset in range(13, -1, -1):
        day = cursor - timedelta(days=offset)
        day_labels.append(day.isoformat())

    searches_over_time = [
        {"date": d, "count": day_counts.get(d, 0)} for d in day_labels
    ]

    return AnalyticsSummary(
        total_searches=total_searches,
        top_queries=top_queries,
        top_categories=top_categories,
        top_brands=top_brands,
        searches_over_time=searches_over_time,
    )


@router.post("/click-out", status_code=204)
def track_click_out(payload: ClickTrackRequest, db: Session = Depends(get_db)):
    db.add(
        AnalyticsEvent(
            event_type="click_out",
            payload={
                "product_id": payload.product_id,
                "offer_id": payload.offer_id,
                "platform": payload.platform,
                "title": payload.title,
                "url": payload.url,
            },
        )
    )
    db.commit()
