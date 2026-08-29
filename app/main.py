import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.database import Base, engine
from sqlalchemy import inspect, text

from app.routers import analytics, assistant, auth, products
from app.routers import admin as admin_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("smartshop.main")

settings = get_settings()

app = FastAPI(
    title="SmartShop AI",
    description="Discover, Compare, and Shop Smarter with AI",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In production, create tables via Alembic migrations (see alembic/).
# create_all() here is a convenience fallback for quick local/dev setups
# without a migration run.
Base.metadata.create_all(bind=engine)


def _ensure_user_role_column() -> None:
    inspector = inspect(engine)
    if "users" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("users")}
    if "role" in columns:
        return
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE users ADD COLUMN role VARCHAR DEFAULT 'user'"))
        connection.execute(text("UPDATE users SET role = 'user' WHERE role IS NULL OR role = ''"))

_ensure_user_role_column()

app.include_router(auth.router)
app.include_router(products.router)
app.include_router(assistant.router)
app.include_router(analytics.router)
app.include_router(admin_router.router)

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "pages", "index.html"))


@app.get("/{page_name}")
def serve_page(page_name: str):
    """
    Serves top-level SPA-ish pages, e.g. /login -> static/pages/login.html.
    Falls back to index.html for unknown paths so client-side routing (if any) works.
    """
    candidate = os.path.join(STATIC_DIR, "pages", f"{page_name}.html")
    if os.path.isfile(candidate):
        return FileResponse(candidate)
    return FileResponse(os.path.join(STATIC_DIR, "pages", "index.html"))
