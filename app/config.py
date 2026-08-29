"""
Centralized configuration. All secrets come from environment variables
(.env locally, real env vars in production). Nothing here is ever hardcoded.
"""
from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database
    DATABASE_URL: str = "sqlite:///./smartshop.db"

    # Apify
    APIFY_API_TOKEN: str = ""
    AMAZON_ACTOR_ID: str = ""
    FLIPKART_ACTOR_ID: str = ""
    APIFY_RUN_TIMEOUT_SECONDS: int = 90

    # LLM
    LLM_PROVIDER: str = "openai"  # openai | azure | none
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"
    # Leave blank to use OpenAI's own endpoint. Set to
    # "https://openrouter.ai/api/v1" (or another OpenAI-compatible provider)
    # if OPENAI_API_KEY is actually a key for that provider, e.g. an
    # OpenRouter key (starts with "sk-or-"). When using OpenRouter, also set
    # OPENAI_MODEL to an OpenRouter model id, e.g. "openai/gpt-4o-mini".
    OPENAI_BASE_URL: str = ""
    AZURE_OPENAI_API_KEY: str = ""
    AZURE_OPENAI_ENDPOINT: str = ""
    AZURE_OPENAI_DEPLOYMENT: str = ""
    AZURE_OPENAI_API_VERSION: str = "2024-02-15-preview"

    # Auth
    JWT_SECRET_KEY: str = "change-me"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440
    ADMIN_INVITE_CODE: str = ""

    # Embeddings
    EMBEDDING_MODEL_NAME: str = "all-MiniLM-L6-v2"
    FAISS_INDEX_DIR: str = "./faiss_index"

    # Misc
    ENVIRONMENT: str = "development"
    CORS_ORIGINS: str = "http://localhost:8000"

    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()