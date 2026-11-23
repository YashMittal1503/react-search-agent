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
    name: str
    base_url: str
    env_prefix: str
    headers: dict[str, str] = field(default_factory=dict)
    timeout: float = 60.0


# Defaults; override or extend under `providers:` in the YAML.
DEFAULT_PROVIDERS: dict[str, ProviderSpec] = {
    "groq": ProviderSpec("groq", "https://api.groq.com/openai/v1", "GROQ"),
    "nvidia": ProviderSpec("nvidia", "https://integrate.api.nvidia.com/v1", "NVIDIA", timeout=90.0),
    "mistral": ProviderSpec("mistral", "https://api.mistral.ai/v1", "MISTRAL"),
    "gemini": ProviderSpec("gemini", "https://generativelanguage.googleapis.com/v1beta/openai/", "GEMINI"),
    "openrouter": ProviderSpec("openrouter", "https://openrouter.ai/api/v1", "OPENROUTER"),
    "cerebras": ProviderSpec("cerebras", "https://api.cerebras.ai/v1", "CEREBRAS"),
}


@dataclass(frozen=True)
class Target:
    provider: str
    model: str
    params: dict[str, Any] = field(default_factory=dict, hash=False, compare=False)

    @property
    def id(self) -> str:
        return f"{self.provider}:{self.model}"


@dataclass
class PoolConfig:
    providers: dict[str, ProviderSpec]
    tiers: dict[str, list[Target]]
    max_wait_seconds: float = 20.0      # wait for a cooling key when nothing else is left
    max_attempts: int = 14              # per call, across all tiers and keys

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PoolConfig":
        providers = dict(DEFAULT_PROVIDERS)
        for name, spec in (data.get("providers") or {}).items():
            base = providers.get(name)
            providers[name] = ProviderSpec(
                name=name,
                base_url=spec.get("base_url", base.base_url if base else ""),
                env_prefix=spec.get("env_prefix", base.env_prefix if base else name.upper()),
                headers={**(base.headers if base else {}), **(spec.get("headers") or {})},
                timeout=float(spec.get("timeout", base.timeout if base else 60.0)),
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
        return cls(
            providers=providers,
            tiers=tiers,
            max_wait_seconds=float(data.get("max_wait_seconds", 20.0)),
            max_attempts=int(data.get("max_attempts", 14)),
        )

    @classmethod
    def from_yaml(cls, path: str | Path) -> "PoolConfig":
        import yaml  # pyyaml

        return cls.from_dict(yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {})
