from __future__ import annotations

import json

import httpx
import pytest

from jingyantai.llm.contracts import (
    ModelInvocation,
    ProviderConfig,
    ProviderRequestError,
    ResponseFormatError,
)
from jingyantai.llm.deepseek_runner import DeepSeekRunner


class FakeResponse:
    def __init__(self, status_code: int, payload: dict[str, object]) -> None:
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "boom",
                request=httpx.Request("POST", "https://api.deepseek.com/chat/completions"),
                response=httpx.Response(self.status_code),
            )

    def json(self) -> dict[str, object]:
        return self._payload


class RecordingClient:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self._responses = responses
        self.calls: list[dict[str, object]] = []

    def post(self, url: str, *, json: dict[str, object], headers: dict[str, str], timeout: float) -> FakeResponse:
        self.calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        return self._responses[min(len(self.calls) - 1, len(self._responses) - 1)]


def _config(*, max_retries: int = 1) -> ProviderConfig:
    return ProviderConfig(
        provider="deepseek",
        model="deepseek-chat",
        base_url="https://api.deepseek.com/",
        api_key_env="DEEPSEEK_API_KEY",
        timeout_seconds=12.5,
        max_retries=max_retries,
    )


def _invocation() -> ModelInvocation:
    return ModelInvocation(
        system_prompt="You are the Lead Researcher.",
        payload={"target": "Claude Code"},
        response_schema_name="LeadResearcherOutput",
        temperature=0.2,
    )


def test_deepseek_runner_posts_to_chat_completions_and_parses_json(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    response = FakeResponse(
        200,
        {"choices": [{"message": {"content": json.dumps({"round_plan": "collect evidence"})}}]},
    )
    client = RecordingClient([response])
    runner = DeepSeekRunner(config=_config(), http_client=client)

    result = runner.run(_invocation())

    assert result == {"round_plan": "collect evidence"}
    assert len(client.calls) == 1
    assert client.calls[0]["url"] == "https://api.deepseek.com/chat/completions"
    assert client.calls[0]["timeout"] == 12.5
    assert client.calls[0]["headers"]["Authorization"] == "Bearer test-key"
    assert client.calls[0]["json"]["model"] == "deepseek-chat"
    assert client.calls[0]["json"]["temperature"] == 0.2
    assert client.calls[0]["json"]["response_format"] == {"type": "json_object"}
    assert isinstance(client.calls[0]["json"]["messages"], list)
    user_content = client.calls[0]["json"]["messages"][1]["content"]
    user_content_json = json.loads(user_content)
    assert user_content_json["schema"] == "LeadResearcherOutput"
    assert user_content_json["payload"] == {"target": "Claude Code"}
    assert user_content_json["instructions"] == "Return JSON only."


def test_deepseek_runner_raises_provider_request_error_after_retry_exhaustion(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    client = RecordingClient([FakeResponse(500, {"error": "boom"})])
    runner = DeepSeekRunner(config=_config(max_retries=2), http_client=client)

    with pytest.raises(ProviderRequestError, match=r"after retries"):
        runner.run(_invocation())

    assert len(client.calls) == 3


def test_deepseek_runner_raises_provider_request_error_when_api_key_missing(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    client = RecordingClient([FakeResponse(200, {"choices": []})])
    runner = DeepSeekRunner(config=_config(max_retries=2), http_client=client)

    with pytest.raises(ProviderRequestError, match=r"Missing API key env: DEEPSEEK_API_KEY"):
        runner.run(_invocation())

    assert len(client.calls) == 0


def test_deepseek_runner_raises_response_format_error_on_non_json_content(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    client = RecordingClient([FakeResponse(200, {"choices": [{"message": {"content": "not-json"}}]})])
    runner = DeepSeekRunner(config=_config(), http_client=client)

    with pytest.raises(ResponseFormatError):
        runner.run(_invocation())


def test_deepseek_runner_raises_response_format_error_on_bad_response_shape(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    client = RecordingClient([FakeResponse(200, {"foo": "bar"})])
    runner = DeepSeekRunner(config=_config(), http_client=client)

    with pytest.raises(ResponseFormatError):
        runner.run(_invocation())
