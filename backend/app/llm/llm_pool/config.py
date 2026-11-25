"""Provider registry and tier configuration.

Tiers are ordered fallback chains of ``provider:model`` targets, loaded from YAML or a dict.
Every provider here speaks the OpenAI chat-completions protocol, so one SDK covers them all.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ProviderSpec:
    """How to reach one provider: its OpenAI-compatible base URL, where its keys live, and its quirks."""

    name: str
    base_url: str
    env_prefix: str          # keys are read from <PREFIX>_API_KEY, <PREFIX>_API_KEY_2.., <PREFIX>_API_KEYS
    headers: dict[str, str] = field(default_factory=dict)
    timeout: float = 60.0
    # Largest request (prompt + max output tokens) one call may carry, e.g. Groq's free 8K tokens/minute.
    # Targets that cannot fit a request are skipped before any call is made.
    max_request_tokens: int | None = None
    # True when every key belongs to ONE account/project: a 429 on one key then cools all of them,
    # instead of burning one request per key to find out. Env override: <PREFIX>_SHARED_QUOTA=true.
    shared_quota: bool = False
    # When daily quotas reset ("UTC", "America/Los_Angeles", ...). None = rolling window (trust Retry-After).
    daily_reset: str | None = None


# Defaults; override or extend under `providers:` in the YAML.
DEFAULT_PROVIDERS: dict[str, ProviderSpec] = {
    "groq": ProviderSpec("groq", "https://api.groq.com/openai/v1", "GROQ"),
    "nvidia": ProviderSpec("nvidia", "https://integrate.api.nvidia.com/v1", "NVIDIA", timeout=90.0),
    "mistral": ProviderSpec("mistral", "https://api.mistral.ai/v1", "MISTRAL"),
    "gemini": ProviderSpec("gemini", "https://generativelanguage.googleapis.com/v1beta/openai/", "GEMINI",
                           daily_reset="America/Los_Angeles"),   # Gemini daily quotas reset at midnight Pacific
    "openrouter": ProviderSpec("openrouter", "https://openrouter.ai/api/v1", "OPENROUTER", daily_reset="UTC"),
    # Cerebras has no lasting free tier (a one-time $5 trial that needs a card); keep the spec for paid use.
    "cerebras": ProviderSpec("cerebras", "https://api.cerebras.ai/v1", "CEREBRAS"),
}


@dataclass(frozen=True)
class Target:
    """One model on one provider, plus extra request params for it (e.g. ``reasoning_effort``)."""

    provider: str
    model: str
    params: dict[str, Any] = field(default_factory=dict, hash=False, compare=False)

    @property
    def id(self) -> str:
        """``"provider:model"``, the key used for cooldowns, limits and logs."""
        return f"{self.provider}:{self.model}"


@dataclass
class PoolConfig:
    """The whole pool configuration: providers, named tiers and retry budgets (usually from ``models.yaml``)."""

    providers: dict[str, ProviderSpec]
    tiers: dict[str, list[Target]]
    max_wait_seconds: float = 20.0      # wait for a cooling key when nothing else is left
    max_attempts: int = 20              # per call, across all tiers and keys
    fallbacks: dict[str, list[str]] = field(default_factory=dict)   # tier -> tiers to borrow targets from
    limits: dict[str, int] = field(default_factory=dict)            # "provider:model" -> max request tokens

    def chain(self, tier: str) -> list[Target]:
        """The tier's own targets, then those of its fallback tiers (in order, each target once)."""
        seen: set[str] = set()
        out: list[Target] = []
        for name in [tier, *self.fallbacks.get(tier, [])]:
            for t in self.tiers.get(name, []):
                if t.id not in seen:
                    seen.add(t.id)
                    out.append(t)
        return out

    def request_limit(self, target: Target) -> int | None:
        """Max tokens one request to ``target`` may carry (per-target ``limits`` beat the provider default)."""
        return self.limits.get(target.id) or self.providers[target.provider].max_request_tokens

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PoolConfig":
        """Build from a parsed YAML/dict, merging provider overrides onto the defaults and validating names.

        Tier entries are either ``"provider:model"`` strings or ``{provider, model, params}`` mappings.

        Raises:
            ValueError: a tier uses an unknown provider, or ``fallbacks`` names an unknown tier.
        """
        providers = dict(DEFAULT_PROVIDERS)
        for name, spec in (data.get("providers") or {}).items():
            base = providers.get(name)
            providers[name] = ProviderSpec(
                name=name,
                base_url=spec.get("base_url", base.base_url if base else ""),
                env_prefix=spec.get("env_prefix", base.env_prefix if base else name.upper()),
                headers={**(base.headers if base else {}), **(spec.get("headers") or {})},
                timeout=float(spec.get("timeout", base.timeout if base else 60.0)),
                max_request_tokens=spec.get("max_request_tokens", base.max_request_tokens if base else None),
                shared_quota=bool(spec.get("shared_quota", base.shared_quota if base else False)),
                daily_reset=spec.get("daily_reset", base.daily_reset if base else None),
            )
        tiers: dict[str, list[Target]] = {}
        for tier, entries in (data.get("tiers") or {}).items():
            targets = []
            for entry in entries:
                if isinstance(entry, str):
                    provider, _, model = entry.partition(":")
                    targets.append(Target(provider.strip(), model.strip()))
                else:
                    targets.append(Target(entry["provider"], entry["model"], dict(entry.get("params") or {})))
            unknown = {t.provider for t in targets} - providers.keys()
            if unknown:
                raise ValueError(f"tier {tier!r} uses unknown providers: {sorted(unknown)}")
            tiers[tier] = targets
        fallbacks = {t: [f] if isinstance(f, str) else list(f) for t, f in (data.get("fallbacks") or {}).items()}
        bad = {f for fs in fallbacks.values() for f in fs} - tiers.keys()
        if bad:
            raise ValueError(f"fallbacks name unknown tiers: {sorted(bad)}")
        return cls(
            providers=providers,
            tiers=tiers,
            fallbacks=fallbacks,
            limits={str(k): int(v) for k, v in (data.get("limits") or {}).items()},
            max_wait_seconds=float(data.get("max_wait_seconds", 20.0)),
            max_attempts=int(data.get("max_attempts", 20)),
        )

    @classmethod
    def from_yaml(cls, path: str | Path) -> "PoolConfig":
        """Load a YAML file (see ``models.example.yaml`` in the skill for the format)."""
        import yaml  # pyyaml

        return cls.from_dict(yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {})
