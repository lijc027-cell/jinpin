from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from jingyantai.agents.deepagents_adapter import DeepagentsRoleAdapter
from jingyantai.llm.contracts import ModelInvocation, ProviderConfig


class OutputModel(BaseModel):
    round_plan: str


class StaticRunner:
    def __init__(self) -> None:
        self.config = ProviderConfig(
            provider="deepseek",
            model="deepseek-chat",
            base_url="https://api.deepseek.com",
            api_key_env="DEEPSEEK_API_KEY",
            timeout_seconds=20.0,
            max_retries=1,
        )
        self.invocations: list[ModelInvocation] = []

    def run(self, invocation: ModelInvocation) -> dict[str, object]:
        self.invocations.append(invocation)
        return {"round_plan": "deepen workflow evidence"}


def test_deepagents_adapter_uses_runner_and_validates_schema():
    runner = StaticRunner()
    adapter = DeepagentsRoleAdapter(role_prompt="You are the Lead Researcher.", runner=runner)

    result = adapter.run({"target": "Claude Code"}, OutputModel)

    assert result.round_plan == "deepen workflow evidence"
    assert runner.invocations[0].response_schema_name == "OutputModel"
    assert adapter.provider == "deepseek"
    assert adapter.model == "deepseek-chat"


def test_deepagents_adapter_raises_validation_error_on_bad_payload():
    runner = StaticRunner()
    runner.run = lambda invocation: {"wrong": "shape"}
    adapter = DeepagentsRoleAdapter(role_prompt="You are the Lead Researcher.", runner=runner)

    with pytest.raises(ValidationError):
        adapter.run({"target": "Claude Code"}, OutputModel)
