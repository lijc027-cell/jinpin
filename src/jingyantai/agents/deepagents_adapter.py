from __future__ import annotations

from typing import Any, TypeVar

from pydantic import BaseModel

from jingyantai.llm.contracts import ModelInvocation, ModelRunner


T = TypeVar("T", bound=BaseModel)


class DeepagentsRoleAdapter:
    def __init__(self, role_prompt: str, runner: ModelRunner) -> None:
        self.role_prompt = role_prompt
        self.runner = runner
        self.provider = runner.config.provider
        self.model = runner.config.model

    def run(self, payload: dict[str, Any], model_type: type[T]) -> T:
        invocation = ModelInvocation(
            system_prompt=self.role_prompt,
            payload=payload,
            response_schema_name=model_type.__name__,
        )
        result = self.runner.run(invocation)
        return model_type.model_validate(result)
