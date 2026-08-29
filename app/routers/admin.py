from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.deps import get_current_admin
from app.models import AnalyticsEvent, User
from app.schemas import AdminSummary

router = APIRouter(prefix="/api/admin", tags=["admin"])
settings = get_settings()


@router.get("/summary", response_model=AdminSummary)
def summary(
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    if current_admin.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access is required.")

    total_users = int(db.execute(text("SELECT COUNT(*) FROM users")).scalar() or 0)
    total_admins = int(db.execute(text("SELECT COUNT(*) FROM users WHERE role = 'admin'")).scalar() or 0)
    total_searches = int(db.execute(text("SELECT COUNT(*) FROM search_history")).scalar() or 0)
    total_comparisons = int(
        db.execute(text("SELECT COUNT(*) FROM analytics_events WHERE event_type = 'compare'")).scalar() or 0
    )
    total_click_throughs = int(
        db.execute(text("SELECT COUNT(*) FROM analytics_events WHERE event_type = 'click_out'")).scalar() or 0
    )

    search_events = (
        db.query(AnalyticsEvent)
        .filter(AnalyticsEvent.event_type == "search")
        .order_by(AnalyticsEvent.created_at.desc())
        .all()
    )
    searches_with_results = 0
    searches_without_results = 0
    warnings_count = 0
    total_results = 0
    recent_searches = []
    for event in search_events:
        payload = event.payload or {}
        result_count = int(payload.get("result_count") or 0)
        total_results += result_count
        if result_count > 0:
            searches_with_results += 1
        else:
            searches_without_results += 1
        warnings = payload.get("warnings") or []
        warnings_count += len(warnings)
        recent_searches.append(
            {
                "query": payload.get("query") or "Unknown query",
                "result_count": result_count,
                "warning_count": len(warnings),
                "created_at": event.created_at.isoformat() if event.created_at else None,
            }
        )

    recent_clicks = (
        db.query(AnalyticsEvent)
        .filter(AnalyticsEvent.event_type == "click_out")
        .order_by(AnalyticsEvent.created_at.desc())
        .limit(10)
        .all()
    )
    recent_click_throughs = [
        {
            "platform": (event.payload or {}).get("platform"),
            "title": (event.payload or {}).get("title") or "Unknown product",
            "url": (event.payload or {}).get("url"),
            "created_at": event.created_at.isoformat() if event.created_at else None,
        }
        for event in recent_clicks
    ]

    average_results_per_search = round(total_results / total_searches, 2) if total_searches else 0.0
    warning_rate_pct = round((warnings_count / total_searches) * 100, 2) if total_searches else 0.0
    click_through_rate_pct = round((total_click_throughs / total_searches) * 100, 2) if total_searches else 0.0

    return AdminSummary(
        total_users=total_users,
        total_admins=total_admins,
        total_searches=total_searches,
        total_comparisons=total_comparisons,
        total_click_throughs=total_click_throughs,
        searches_with_results=searches_with_results,
        searches_without_results=searches_without_results,
        average_results_per_search=average_results_per_search,
        warning_rate_pct=warning_rate_pct,
        click_through_rate_pct=click_through_rate_pct,
        llm_provider=settings.LLM_PROVIDER,
        apify_configured=bool(settings.APIFY_API_TOKEN and settings.AMAZON_ACTOR_ID and settings.FLIPKART_ACTOR_ID),
        recent_searches=recent_searches[:10],
        recent_click_throughs=recent_click_throughs,
    )