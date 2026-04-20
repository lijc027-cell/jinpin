from __future__ import annotations

from time import perf_counter
from typing import Callable
from typing import Any, TypeVar

from pydantic import BaseModel

from jingyantai.llm.contracts import ModelInvocation, ModelRunner


T = TypeVar("T", bound=BaseModel)


class DeepagentsRoleAdapter:
    PHASE_TIMEOUT_BUDGET_SHARE = 0.5

    def __init__(
        self,
        role_prompt: str,
        runner: ModelRunner,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.role_prompt = role_prompt
        self.runner = runner
        self.provider = runner.config.provider
        self.model = runner.config.model
        self._clock = clock or perf_counter
        self._runtime_deadline_at: float | None = None

    def set_runtime_deadline(self, deadline_at: float | None) -> None:
        self._runtime_deadline_at = deadline_at

    def clear_runtime_deadline(self) -> None:
        self._runtime_deadline_at = None

    def _remaining_timeout_seconds(self) -> float | None:
        if self._runtime_deadline_at is None:
            return None
        return max(self._runtime_deadline_at - self._clock(), 0.0)

    def run(self, payload: dict[str, Any], model_type: type[T]) -> T:
        remaining_timeout = self._remaining_timeout_seconds()
        if remaining_timeout is not None and remaining_timeout <= 0:
            raise TimeoutError("phase runtime deadline exceeded before model invocation")
        timeout_override = None
        if remaining_timeout is not None:
            timeout_override = min(
                self.runner.config.timeout_seconds,
                remaining_timeout,
                max(1.0, remaining_timeout * self.PHASE_TIMEOUT_BUDGET_SHARE),
            )
        invocation = ModelInvocation(
            system_prompt=self.role_prompt,
            payload=payload,
            response_schema_name=model_type.__name__,
            response_schema=model_type.model_json_schema(),
            timeout_seconds=timeout_override,
        )
        result = self.runner.run(invocation)
        return model_type.model_validate(result)
