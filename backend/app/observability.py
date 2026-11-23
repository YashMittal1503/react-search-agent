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
        # LangSmith reads LANGSMITH_* env vars itself; make sure .env values reach os.environ.
        if s.langsmith_tracing:
            os.environ.setdefault("LANGSMITH_TRACING", "true")
    if app is not None:
        try:
            import logfire

            logfire.instrument_fastapi(app, excluded_urls="/health")
        except Exception as err:  # pragma: no cover
            logger.warning("logfire fastapi instrumentation skipped: %s", err)
