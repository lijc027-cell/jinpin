from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class DeepagentsRoleAdapter:
    def __init__(self, role_prompt: str, runner) -> None:
        self.role_prompt = role_prompt
        self.runner = runner

    def run(self, payload: dict[str, Any], model_type: type[BaseModel]):
        result = self.runner(self.role_prompt, payload)
        return model_type.model_validate(result)
