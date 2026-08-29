from datetime import datetime
from typing import Any, Dict, List, Optional, Literal

from pydantic import BaseModel, EmailStr, Field


# ---------- Auth ----------
class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    full_name: Optional[str] = None
    role: Literal["user", "admin"] = "user"
    invite_code: Optional[str] = None


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: str
    email: EmailStr
    full_name: Optional[str] = None
    role: Literal["user", "admin"] = "user"

    class Config:
        from_attributes = True


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ---------- Offers / Products ----------
class OfferOut(BaseModel):
    id: str
    platform: str
    title: str
    url: str
    image_url: Optional[str] = None
    price: Optional[float] = None
    currency: str = "INR"
    rating: Optional[float] = None
    review_count: Optional[int] = None
    availability: Optional[str] = None
    raw_specifications: Optional[Dict[str, Any]] = None
    fetched_at: Optional[datetime] = None
    is_stale: bool = False

    class Config:
        from_attributes = True


class ProductOut(BaseModel):
    id: str
    canonical_title: str
    brand: Optional[str] = None
    category: Optional[str] = None
    specifications: Optional[Dict[str, Any]] = None
    primary_image_url: Optional[str] = None
    offers: List[OfferOut] = []
    ai_reason: Optional[str] = None
    best_price: Optional[float] = None
    best_platform: Optional[str] = None
    avg_rating: Optional[float] = None
    total_reviews: Optional[int] = None

    class Config:
        from_attributes = True


class SearchRequest(BaseModel):
    query: str
    max_price: Optional[float] = None
    min_rating: Optional[float] = None
    category: Optional[str] = None
    limit: int = 20


class SearchResponse(BaseModel):
    query: str
    total_results: int
    products: List[ProductOut]
    warnings: List[str] = []


# ---------- Comparison ----------
class CompareRequest(BaseModel):
    product_ids: List[str] = Field(min_length=2, max_length=5)


class CompareResult(BaseModel):
    products: List[ProductOut]
    comparison_table: Dict[str, Dict[str, Any]]
    pros_cons: Dict[str, Dict[str, List[str]]]
    ai_summaries: Dict[str, str] = {}
    best_overall: Optional[str] = None
    best_value: Optional[str] = None
    explanation: str


# ---------- Cross platform ----------
class CrossPlatformResult(BaseModel):
    product: ProductOut
    ai_verdict: str
    best_platform: Optional[str] = None
    amazon_explanation: Optional[str] = None
    flipkart_explanation: Optional[str] = None


# ---------- Reviews / sentiment ----------
class ReviewSummary(BaseModel):
    product_id: str
    total_reviews_analyzed: int
    positive_pct: float
    neutral_pct: float
    negative_pct: float
    common_positive_points: List[str]
    common_complaints: List[str]
    summary_text: str


# ---------- Assistant / RAG ----------
class AssistantQuery(BaseModel):
    question: str
    product_id: Optional[str] = None
    conversation_id: Optional[str] = None


class AssistantAnswer(BaseModel):
    answer: str
    sources: List[str] = []


# ---------- Recommendations ----------
class RecommendationOut(BaseModel):
    product: ProductOut
    reason: str
    rec_type: str


# ---------- Analytics ----------
class AnalyticsSummary(BaseModel):
    total_searches: int
    top_queries: List[Dict[str, Any]]
    top_categories: List[Dict[str, Any]]
    top_brands: List[Dict[str, Any]]
    searches_over_time: List[Dict[str, Any]]


class ClickTrackRequest(BaseModel):
    product_id: Optional[str] = None
    offer_id: Optional[str] = None
    platform: Optional[str] = None
    title: Optional[str] = None
    url: Optional[str] = None


class AdminSummary(BaseModel):
    total_users: int
    total_admins: int
    total_searches: int
    total_comparisons: int
    total_click_throughs: int
    searches_with_results: int
    searches_without_results: int
    average_results_per_search: float
    warning_rate_pct: float
    click_through_rate_pct: float
    llm_provider: str
    apify_configured: bool
    recent_searches: List[Dict[str, Any]]
    recent_click_throughs: List[Dict[str, Any]]
