"""Logfire (app/HTTP spans) + LangSmith (agent traces). Both optional, both free tiers."""

import logging
import os

from .settings import get_settings

logger = logging.getLogger(__name__)
_configured = False


def setup_observability(app=None) -> None:
    global _configured
    s = get_settings()
    if not _configured:
        _configured = True
        try:
            import logfire

            logfire.configure(
                token=s.logfire_token or None,
                send_to_logfire="if-token-present",
                service_name="react-search-agent",
                console=False,
                scrubbing=logfire.ScrubbingOptions(extra_patterns=["api_key", "authorization"]),
            )
            logfire.instrument_httpx(capture_all=False)
        except Exception as err:  # pragma: no cover
            logger.warning("logfire setup skipped: %s", err)
        _setup_langsmith(s)
    if app is not None:
        try:
            import logfire

            logfire.instrument_fastapi(app, excluded_urls="/health")
        except Exception as err:  # pragma: no cover
            logger.warning("logfire fastapi instrumentation skipped: %s", err)


def _setup_langsmith(s) -> None:
    """LangSmith reads LANGSMITH_* from os.environ (not from pydantic settings).

    Tracing turns on when an API key is present, unless LANGSMITH_TRACING=false is set explicitly.
    """
    from dotenv import load_dotenv

    from .settings import BACKEND_DIR

    load_dotenv(BACKEND_DIR / ".env")
    key = os.environ.get("LANGSMITH_API_KEY") or os.environ.get("LANGCHAIN_API_KEY")
    explicit = os.environ.get("LANGSMITH_TRACING") or os.environ.get("LANGCHAIN_TRACING_V2")
    if key and (s.langsmith_tracing or explicit is None):
        os.environ["LANGSMITH_TRACING"] = "true"
    if os.environ.get("LANGSMITH_TRACING", "").lower() == "true":
        os.environ.setdefault("LANGSMITH_PROJECT", "react-search-agent")
        logger.info("LangSmith tracing on (project %s)", os.environ["LANGSMITH_PROJECT"])


def flush_traces() -> None:
    """Short-lived processes (CLI, evals) must wait for LangSmith's background uploader before exiting."""
    try:
        from langchain_core.tracers.langchain import wait_for_all_tracers

        wait_for_all_tracers()
    except Exception:  # pragma: no cover
        pass
