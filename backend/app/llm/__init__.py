"""One shared LLM router per process (cooldown state lives on it)."""

from functools import lru_cache

from dotenv import load_dotenv

from ..settings import BACKEND_DIR, get_settings
from .llm_pool import LLMRouter, PoolConfig
from .llm_pool.langchain_model import PooledChatModel

load_dotenv(BACKEND_DIR / ".env")


@lru_cache
def get_router() -> LLMRouter:
    return LLMRouter(PoolConfig.from_yaml(get_settings().models_config))


def chat_model(tier: str, temperature: float = 0.2, max_tokens: int | None = None) -> PooledChatModel:
    return PooledChatModel(router=get_router(), tier=tier, temperature=temperature, max_tokens=max_tokens)
