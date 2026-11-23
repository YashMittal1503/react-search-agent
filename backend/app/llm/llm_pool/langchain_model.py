"""LangChain adapter: a ``BaseChatModel`` that rotates keys and fails over across a tier.

Works anywhere a chat model is expected (LangGraph, ``create_agent``, deepagents):
``bind_tools``, ``with_structured_output``, sync/async invoke and streaming.

    router = LLMRouter(PoolConfig.from_yaml("models.yaml"))
    llm = PooledChatModel(router=router, tier="agent", temperature=0.2)
    llm.bind_tools([my_tool]).invoke("...")
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator, Callable, Iterator, Sequence

from langchain_core.callbacks import AsyncCallbackManagerForLLMRun, CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatGenerationChunk, ChatResult
from langchain_core.tools import BaseTool
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import ConfigDict, Field

from .router import Attempt, LLMRouter

_DROP_KWARGS = ("ls_structured_output_format",)


def _normalize_tool_choice(choice: Any) -> Any:
    if choice is None or choice is False:
        return None
    if choice is True or choice == "any":
        return "required"
    if isinstance(choice, str) and choice not in ("auto", "none", "required"):
        return {"type": "function", "function": {"name": choice}}
    return choice


class PooledChatModel(BaseChatModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    router: LLMRouter = Field(exclude=True)
    tier: str = "default"
    temperature: float | None = 0.2
    max_tokens: int | None = None
    timeout: float | None = None
    extra_params: dict[str, Any] = Field(default_factory=dict)

    @property
    def _llm_type(self) -> str:
        return "llm-pool"

    @property
    def _identifying_params(self) -> dict[str, Any]:
        return {"tier": self.tier, "temperature": self.temperature, "max_tokens": self.max_tokens}

    # ── per-attempt ChatOpenAI ───────────────────────────────────────────
    def _chat(self, attempt: Attempt):
        from langchain_openai import ChatOpenAI

        params = {**attempt.target.params, **self.extra_params}
        cache_key = ("lc", attempt.target.id, self.temperature, self.max_tokens, tuple(sorted(map(str, params.items()))))
        chat = attempt.slot.cache.get(cache_key)
        if chat is None:
            kwargs: dict[str, Any] = dict(
                model=attempt.target.model,
                api_key=attempt.key,
                base_url=attempt.spec.base_url,
                max_retries=0,
                timeout=self.timeout or attempt.spec.timeout,
                stream_usage=False,   # not every OpenAI-compatible provider accepts stream_options
            )
            if self.temperature is not None:
                kwargs["temperature"] = self.temperature
            if self.max_tokens is not None:
                kwargs["max_tokens"] = self.max_tokens
            if attempt.spec.headers:
                kwargs["default_headers"] = attempt.spec.headers
            if params:
                kwargs["model_kwargs"] = params
            chat = ChatOpenAI(**kwargs)
            attempt.slot.cache[cache_key] = chat
        return chat

    @staticmethod
    def _tag(result: ChatResult, attempt: Attempt) -> ChatResult:
        for gen in result.generations:
            meta = gen.message.response_metadata
            meta["llm_pool_target"] = attempt.target.id
            meta["llm_pool_key"] = attempt.slot.masked_key
        result.llm_output = {**(result.llm_output or {}), "llm_pool_target": attempt.target.id}
        return result

    @staticmethod
    def _clean(kwargs: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in kwargs.items() if k not in _DROP_KWARGS and v is not None}

    # ── generation ───────────────────────────────────────────────────────
    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        kwargs = self._clean(kwargs)

        async def call(attempt: Attempt) -> ChatResult:
            result = await self._chat(attempt)._agenerate(messages, stop=stop, **kwargs)
            return self._tag(result, attempt)

        return await self.router.run(self.tier, call)

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self._agenerate(messages, stop=stop, **kwargs))
        raise RuntimeError("PooledChatModel: use ainvoke() inside a running event loop")

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        kwargs = self._clean(kwargs)

        async def call(attempt: Attempt) -> AsyncIterator[ChatGenerationChunk]:
            first = True
            async for chunk in self._chat(attempt)._astream(messages, stop=stop, **kwargs):
                if first:
                    chunk.message.response_metadata["llm_pool_target"] = attempt.target.id
                    first = False
                yield chunk

        async for chunk in self.router.run_stream(self.tier, call):
            if run_manager:
                await run_manager.on_llm_new_token(chunk.text, chunk=chunk)
            yield chunk

    def _stream(self, *args: Any, **kwargs: Any) -> Iterator[ChatGenerationChunk]:
        raise NotImplementedError("PooledChatModel streams asynchronously: use astream()")

    # ── tools ────────────────────────────────────────────────────────────
    def bind_tools(
        self,
        tools: Sequence[dict[str, Any] | type | Callable | BaseTool],
        *,
        tool_choice: str | dict | bool | None = None,
        strict: bool | None = None,
        **kwargs: Any,
    ):
        formatted = [convert_to_openai_tool(t, strict=strict) for t in tools]
        choice = _normalize_tool_choice(tool_choice)
        if choice is not None:
            kwargs["tool_choice"] = choice
        return super().bind(tools=formatted, **kwargs)
