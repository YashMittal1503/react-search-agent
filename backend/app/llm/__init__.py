"""LLM access for the whole app, built on the vendored ``llm_pool`` package.

One :class:`LLMRouter` per process holds the API-key pool and every (key, model) cooldown, so it must be shared:
creating routers per request would forget which keys are rate-limited. Tiers (``fast``, ``agent``, ``deep``,
``long_context``, ``judge``) are fallback chains of provider/model targets defined in ``models.yaml``.
"""

from functools import lru_cache

from dotenv import load_dotenv

from ..settings import BACKEND_DIR, get_settings
from .llm_pool import LLMRouter, PoolConfig
from .llm_pool.langchain_model import PooledChatModel

# Provider keys (GROQ_API_KEY, GEMINI_API_KEY, ...) are read from os.environ by llm_pool, not via pydantic settings.
load_dotenv(BACKEND_DIR / ".env")


@lru_cache
def get_router() -> LLMRouter:
    """The process-wide router (created on first use from ``models.yaml``)."""
    return LLMRouter(PoolConfig.from_yaml(get_settings().models_config))


def chat_model(tier: str, temperature: float = 0.2, max_tokens: int | None = None) -> PooledChatModel:
    """A LangChain chat model that fails over across the keys and models of ``tier``.

    It supports ``bind_tools``, ``with_structured_output`` and streaming, so it plugs straight into
    ``create_agent``, ``create_deep_agent`` and LangGraph nodes.
    """
    return PooledChatModel(router=get_router(), tier=tier, temperature=temperature, max_tokens=max_tokens)
