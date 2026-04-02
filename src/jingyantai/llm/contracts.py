from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ProviderConfig:
    provider: str
    model: str
    base_url: str
    api_key_env: str
    timeout_seconds: float = 20.0
    max_retries: int = 1


@dataclass(frozen=True)
class ModelInvocation:
    system_prompt: str
    payload: dict[str, Any]
    response_schema_name: str
    temperature: float = 0.0


class ModelRunnerError(Exception):
    pass


class ProviderRequestError(ModelRunnerError):
    pass


class ResponseFormatError(ModelRunnerError):
    pass


class ModelRunner(Protocol):
    config: ProviderConfig

    def run(self, invocation: ModelInvocation) -> dict[str, Any]: ...
