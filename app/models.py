import uuid
from datetime import datetime

from sqlalchemy import (
    Column, String, Integer, Float, Boolean, DateTime, ForeignKey, Text, JSON
)
from sqlalchemy.orm import relationship

from app.database import Base


def gen_uuid() -> str:
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=gen_uuid)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    full_name = Column(String, nullable=True)
    role = Column(String, nullable=False, default="user", index=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    search_history = relationship("SearchHistory", back_populates="user")
    comparisons = relationship("Comparison", back_populates="user")


class Product(Base):
    """
    A canonical product entity. The SAME real-world product may have
    multiple PlatformOffer rows (Amazon, Flipkart) linked to it, which is
    what enables cross-platform comparison.
    """
    __tablename__ = "products"

    id = Column(String, primary_key=True, default=gen_uuid)
    canonical_title = Column(String, nullable=False, index=True)
    brand = Column(String, nullable=True, index=True)
    category = Column(String, nullable=True, index=True)
    normalized_key = Column(String, nullable=True, index=True)  # used for dedupe matching
    specifications = Column(JSON, nullable=True)  # dict of spec_name -> value
    primary_image_url = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    offers = relationship("PlatformOffer", back_populates="product", cascade="all, delete-orphan")
    reviews = relationship("Review", back_populates="product", cascade="all, delete-orphan")
    embedding = relationship("EmbeddingMetadata", back_populates="product", uselist=False,
                              cascade="all, delete-orphan")


class PlatformOffer(Base):
    """
    One listing of a product on one platform (Amazon or Flipkart), sourced
    live from Apify. Stores the REAL product URL so we never fabricate links.
    """
    __tablename__ = "platform_offers"

    id = Column(String, primary_key=True, default=gen_uuid)
    product_id = Column(String, ForeignKey("products.id"), nullable=False)

    platform = Column(String, nullable=False, index=True)  # "amazon" | "flipkart"
    platform_product_id = Column(String, nullable=True, index=True)  # ASIN / Flipkart pid
    title = Column(String, nullable=False)
    url = Column(String, nullable=False)  # REAL product URL from Apify, never invented
    image_url = Column(String, nullable=True)
    price = Column(Float, nullable=True)
    currency = Column(String, default="INR")
    rating = Column(Float, nullable=True)
    review_count = Column(Integer, nullable=True)
    availability = Column(String, nullable=True)
    raw_specifications = Column(JSON, nullable=True)
    raw_payload = Column(JSON, nullable=True)  # full raw Apify item, for auditability
    fetched_at = Column(DateTime, default=datetime.utcnow)
    is_stale = Column(Boolean, default=False)

    product = relationship("Product", back_populates="offers")
    reviews = relationship("Review", back_populates="offer", cascade="all, delete-orphan")


class Review(Base):
    __tablename__ = "reviews"

    id = Column(String, primary_key=True, default=gen_uuid)
    product_id = Column(String, ForeignKey("products.id"), nullable=False)
    offer_id = Column(String, ForeignKey("platform_offers.id"), nullable=True)

    platform = Column(String, nullable=True)
    author = Column(String, nullable=True)
    rating = Column(Float, nullable=True)
    title = Column(String, nullable=True)
    body = Column(Text, nullable=True)
    sentiment_label = Column(String, nullable=True)  # positive | neutral | negative
    sentiment_score = Column(Float, nullable=True)
    review_date = Column(DateTime, nullable=True)
    fetched_at = Column(DateTime, default=datetime.utcnow)

    product = relationship("Product", back_populates="reviews")
    offer = relationship("PlatformOffer", back_populates="reviews")


class SearchHistory(Base):
    __tablename__ = "search_history"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=True)
    query = Column(String, nullable=False, index=True)
    category_guess = Column(String, nullable=True)
    budget_max = Column(Float, nullable=True)
    result_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    user = relationship("User", back_populates="search_history")


class Comparison(Base):
    __tablename__ = "comparisons"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=True)
    product_ids = Column(JSON, nullable=False)  # list of product IDs compared
    result_summary = Column(JSON, nullable=True)  # AI verdict payload
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="comparisons")


class Recommendation(Base):
    __tablename__ = "recommendations"

    id = Column(String, primary_key=True, default=gen_uuid)
    source_product_id = Column(String, ForeignKey("products.id"), nullable=False)
    recommended_product_id = Column(String, ForeignKey("products.id"), nullable=False)
    reason = Column(String, nullable=True)
    rec_type = Column(String, nullable=True)  # similar | better_alternative | budget | premium
    score = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class AnalyticsEvent(Base):
    __tablename__ = "analytics_events"

    id = Column(String, primary_key=True, default=gen_uuid)
    event_type = Column(String, nullable=False, index=True)  # search | view | compare | click_out
    user_id = Column(String, ForeignKey("users.id"), nullable=True)
    payload = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class EmbeddingMetadata(Base):
    """
    Maps a product to its position/id inside the FAISS index, so we can
    resync the index and know which vector belongs to which product.
    """
    __tablename__ = "embedding_metadata"

    id = Column(String, primary_key=True, default=gen_uuid)
    product_id = Column(String, ForeignKey("products.id"), unique=True, nullable=False)
    faiss_index_position = Column(Integer, nullable=True)
    embedding_text = Column(Text, nullable=True)  # text that was embedded, for debugging
    model_name = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    product = relationship("Product", back_populates="embedding")
