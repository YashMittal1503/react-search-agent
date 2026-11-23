"""llm_pool: round-robin API-key pool + multi-tier, multi-provider LLM fallback.

Core (needs only ``openai``):      LLMRouter, PoolConfig, Target, load_keys, classify_error
LangChain adapter (optional):      from llm_pool.langchain_model import PooledChatModel
"""

from .config import DEFAULT_PROVIDERS, PoolConfig, ProviderSpec, Target
from .errors import ErrorKind, classify_error, parse_duration, retry_after_seconds
from .keys import load_keys, mask_key
from .pool import KeySlot, ProviderKeyPool
from .router import AllProvidersFailed, Attempt, LLMRouter

__all__ = [
    "AllProvidersFailed", "Attempt", "DEFAULT_PROVIDERS", "ErrorKind", "KeySlot", "LLMRouter", "PoolConfig",
    "ProviderKeyPool", "ProviderSpec", "Target", "classify_error", "load_keys", "mask_key", "parse_duration",
    "retry_after_seconds",
]
