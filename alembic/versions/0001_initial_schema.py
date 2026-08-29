"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-08-29

"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "users",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("email", sa.String(), nullable=False, unique=True, index=True),
        sa.Column("hashed_password", sa.String(), nullable=False),
        sa.Column("full_name", sa.String(), nullable=True),
        sa.Column("is_active", sa.Boolean(), default=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "products",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("canonical_title", sa.String(), nullable=False, index=True),
        sa.Column("brand", sa.String(), nullable=True, index=True),
        sa.Column("category", sa.String(), nullable=True, index=True),
        sa.Column("normalized_key", sa.String(), nullable=True, index=True),
        sa.Column("specifications", sa.JSON(), nullable=True),
        sa.Column("primary_image_url", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "platform_offers",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("product_id", sa.String(), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("platform", sa.String(), nullable=False, index=True),
        sa.Column("platform_product_id", sa.String(), nullable=True, index=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("image_url", sa.String(), nullable=True),
        sa.Column("price", sa.Float(), nullable=True),
        sa.Column("currency", sa.String(), default="INR"),
        sa.Column("rating", sa.Float(), nullable=True),
        sa.Column("review_count", sa.Integer(), nullable=True),
        sa.Column("availability", sa.String(), nullable=True),
        sa.Column("raw_specifications", sa.JSON(), nullable=True),
        sa.Column("raw_payload", sa.JSON(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(), nullable=True),
        sa.Column("is_stale", sa.Boolean(), default=False),
    )

    op.create_table(
        "reviews",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("product_id", sa.String(), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("offer_id", sa.String(), sa.ForeignKey("platform_offers.id"), nullable=True),
        sa.Column("platform", sa.String(), nullable=True),
        sa.Column("author", sa.String(), nullable=True),
        sa.Column("rating", sa.Float(), nullable=True),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("sentiment_label", sa.String(), nullable=True),
        sa.Column("sentiment_score", sa.Float(), nullable=True),
        sa.Column("review_date", sa.DateTime(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "search_history",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("query", sa.String(), nullable=False, index=True),
        sa.Column("category_guess", sa.String(), nullable=True),
        sa.Column("budget_max", sa.Float(), nullable=True),
        sa.Column("result_count", sa.Integer(), default=0),
        sa.Column("created_at", sa.DateTime(), nullable=True, index=True),
    )

    op.create_table(
        "comparisons",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("product_ids", sa.JSON(), nullable=False),
        sa.Column("result_summary", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "recommendations",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("source_product_id", sa.String(), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("recommended_product_id", sa.String(), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("reason", sa.String(), nullable=True),
        sa.Column("rec_type", sa.String(), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "analytics_events",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("event_type", sa.String(), nullable=False, index=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True, index=True),
    )

    op.create_table(
        "embedding_metadata",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("product_id", sa.String(), sa.ForeignKey("products.id"), nullable=False, unique=True),
        sa.Column("faiss_index_position", sa.Integer(), nullable=True),
        sa.Column("embedding_text", sa.Text(), nullable=True),
        sa.Column("model_name", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )


def downgrade():
    op.drop_table("embedding_metadata")
    op.drop_table("analytics_events")
    op.drop_table("recommendations")
    op.drop_table("comparisons")
    op.drop_table("search_history")
    op.drop_table("reviews")
    op.drop_table("platform_offers")
    op.drop_table("products")
    op.drop_table("users")
