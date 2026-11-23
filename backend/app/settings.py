"""App settings, read from environment variables and ``backend/.env`` (pydantic-settings).

Field names map to upper-case env vars (``rate_limit_per_day`` <- ``RATE_LIMIT_PER_DAY``). LLM provider keys are
*not* here: ``llm_pool`` reads them straight from the environment (see ``app/llm/__init__.py``).
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent   # .../backend; default paths below are relative to it


class Settings(BaseSettings):
    """All tunables in one place. Defaults are chosen to fit inside free-tier quotas."""

    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", extra="ignore")

    # search
    tavily_api_key: str = ""
    exa_api_key: str = ""
    searxng_url: str = ""
    jina_api_key: str = ""                # optional; only raises r.jina.ai reader limits

    # fetch
    enable_browser_fetch: bool = False    # crawl4ai/Playwright tier for JS-heavy pages (needs `pip install crawl4ai`)
    allow_private_fetch: bool = False   # SSRF guard: never fetch localhost/private IPs unless explicitly allowed (evals)
    fetch_timeout: float = 15.0           # seconds per HTTP fetch attempt
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/142.0 Safari/537.36 react-search-agent/0.1 (+https://github.com/YashMittal1503/react-search-agent)"
    )

    # observability
    logfire_token: str = ""
    langsmith_tracing: bool = False       # force tracing on; by default it turns on whenever LANGSMITH_API_KEY is set

    # app
    database_url: str = f"sqlite+aiosqlite:///{(BACKEND_DIR / 'data' / 'app.db').as_posix()}"
    checkpoint_path: str = str(BACKEND_DIR / "data" / "checkpoints.sqlite")
    cache_dir: str = str(BACKEND_DIR / "data" / "cache")
    models_config: str = str(BACKEND_DIR / "app" / "llm" / "models.yaml")
    frontend_origins: str = "http://localhost:3000"   # comma-separated CORS origins
    rate_limit_per_day: int = 60          # chat turns per IP per day
    deep_rate_limit_per_day: int = 10     # forced deep-research turns per IP per day (the expensive ones)

    # agent budgets
    quick_max_model_calls: int = 6        # LLM calls the quick ReAct agent may make per turn
    deep_max_model_calls: int = 16        # LLM calls the deep planner may make (subagents have their own cap)
    deep_timeout_seconds: float = 170     # wall-clock budget for deep research before the writer takes over
    max_sources_in_context: int = 14      # sources shown to the writer
    chunk_tokens_per_page: int = 800      # how much of each fetched page the model sees (best BM25 passages)


@lru_cache
def get_settings() -> Settings:
    """The process-wide settings object (cached; evals mutate it, e.g. to allow fetching the local fixture site)."""
    return Settings()
