"""
Thin wrapper so the rest of the app doesn't care whether we're using
OpenAI or Azure OpenAI. If LLM_PROVIDER=none or no key is set, `available`
is False and callers fall back to deterministic heuristics instead of
hallucinating.
"""
import logging
from typing import List, Optional

from app.config import get_settings

logger = logging.getLogger("smartshop.llm")
settings = get_settings()


class LLMClient:
    def __init__(self):
        self.provider = settings.LLM_PROVIDER
        self._chat_model = None
        self.available = False
        self._init_client()

    def _init_client(self):
        try:
            if self.provider == "openai" and settings.OPENAI_API_KEY:
                from langchain_openai import ChatOpenAI

                kwargs = dict(
                    model=settings.OPENAI_MODEL,
                    api_key=settings.OPENAI_API_KEY,
                    temperature=0.2,
                )
                if settings.OPENAI_BASE_URL:
                    kwargs["base_url"] = settings.OPENAI_BASE_URL
                elif settings.OPENAI_API_KEY.startswith("sk-or-"):
                    # Key looks like an OpenRouter key but no base_url was
                    # configured - point at OpenRouter automatically instead
                    # of silently sending it to api.openai.com, where it will
                    # always 401.
                    logger.warning(
                        "OPENAI_API_KEY looks like an OpenRouter key (sk-or-...) but "
                        "OPENAI_BASE_URL isn't set - defaulting to https://openrouter.ai/api/v1. "
                        "Set OPENAI_BASE_URL explicitly to silence this warning, and make sure "
                        "OPENAI_MODEL is an OpenRouter model id (e.g. 'openai/gpt-4o-mini')."
                    )
                    kwargs["base_url"] = "https://openrouter.ai/api/v1"
                self._chat_model = ChatOpenAI(**kwargs)
                self.available = True
            elif self.provider == "azure" and settings.AZURE_OPENAI_API_KEY:
                from langchain_openai import AzureChatOpenAI

                self._chat_model = AzureChatOpenAI(
                    azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
                    api_key=settings.AZURE_OPENAI_API_KEY,
                    api_version=settings.AZURE_OPENAI_API_VERSION,
                    azure_deployment=settings.AZURE_OPENAI_DEPLOYMENT,
                    temperature=0.2,
                )
                self.available = True
        except Exception as exc:  # pragma: no cover
            logger.error("Failed to initialize LLM client: %s", exc)
            self.available = False

    def complete(self, system_prompt: str, user_prompt: str) -> Optional[str]:
        if not self.available or not self._chat_model:
            return None
        try:
            from langchain_core.messages import HumanMessage, SystemMessage

            messages = [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
            response = self._chat_model.invoke(messages)
            return response.content
        except Exception as exc:
            logger.error("LLM completion failed: %s", exc)
            if "401" in str(exc) or "invalid_api_key" in str(exc).lower() or "api key" in str(exc).lower():
                logger.warning("Disabling LLM client because the configured API key is invalid or expired.")
                self.available = False
                self._chat_model = None
            return None


llm_client = LLMClient()