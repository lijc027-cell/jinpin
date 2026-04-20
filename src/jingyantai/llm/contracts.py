from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ProviderConfig:
    provider: str
    model: str
    base_url: str
    api_key_env: str
    timeout_seconds: float = 60.0
    max_retries: int = 1


@dataclass(frozen=True)
class ModelInvocation:
    system_prompt: str
    payload: dict[str, Any]
    response_schema_name: str
    response_schema: dict[str, Any]
    temperature: float = 0.0
    timeout_seconds: float | None = None


class ModelRunnerError(Exception):
    pass


class ProviderRequestError(ModelRunnerError):
    pass


class ResponseFormatError(ModelRunnerError):
    pass


class ModelRunner(Protocol):
    config: ProviderConfig

    def run(self, invocation: ModelInvocation) -> dict[str, Any]: ...
