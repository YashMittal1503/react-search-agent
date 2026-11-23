"""App settings (env / .env)."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", extra="ignore")

    # search
    tavily_api_key: str = ""
    exa_api_key: str = ""
    searxng_url: str = ""
    jina_api_key: str = ""

    # fetch
    enable_browser_fetch: bool = False
    fetch_timeout: float = 15.0
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/142.0 Safari/537.36 react-search-agent/0.1 (+https://github.com/YashMittal1503/react-search-agent)"
    )

    # observability
    logfire_token: str = ""
    langsmith_tracing: bool = False

    # app
    database_url: str = f"sqlite+aiosqlite:///{(BACKEND_DIR / 'data' / 'app.db').as_posix()}"
    checkpoint_path: str = str(BACKEND_DIR / "data" / "checkpoints.sqlite")
    cache_dir: str = str(BACKEND_DIR / "data" / "cache")
    models_config: str = str(BACKEND_DIR / "app" / "llm" / "models.yaml")
    frontend_origins: str = "http://localhost:3000"
    rate_limit_per_day: int = 60
    deep_rate_limit_per_day: int = 10

    # agent budgets
    quick_max_model_calls: int = 6
    deep_max_model_calls: int = 24
    max_sources_in_context: int = 14
    chunk_tokens_per_page: int = 1200


@lru_cache
def get_settings() -> Settings:
    return Settings()
