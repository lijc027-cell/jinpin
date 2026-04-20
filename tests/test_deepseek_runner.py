from __future__ import annotations

from dataclasses import replace
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
        response_schema={
            "type": "object",
            "properties": {
                "round_plan": {"type": "string"},
            },
            "required": ["round_plan"],
        },
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
    assert user_content_json["response_schema"]["required"] == ["round_plan"]
    assert user_content_json["payload"] == {"target": "Claude Code"}
    assert user_content_json["instructions"] == "Return JSON only. Do not wrap the answer in schema or payload fields."


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


def test_deepseek_runner_disables_env_proxy_for_default_httpx_requests(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    captured: dict[str, object] = {}

    def fake_post(url: str, *, json: dict[str, object], headers: dict[str, str], timeout: float, trust_env: bool):
        captured["url"] = url
        captured["trust_env"] = trust_env
        return FakeResponse(
            200,
            {"choices": [{"message": {"content": '{"round_plan":"collect evidence"}'}}]},
        )

    monkeypatch.setattr("jingyantai.llm.deepseek_runner.httpx.post", fake_post)
    runner = DeepSeekRunner(config=_config())

    result = runner.run(_invocation())

    assert result == {"round_plan": "collect evidence"}
    assert captured["url"] == "https://api.deepseek.com/chat/completions"
    assert captured["trust_env"] is False


def test_deepseek_runner_prefers_invocation_timeout_override(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    response = FakeResponse(
        200,
        {"choices": [{"message": {"content": json.dumps({"round_plan": "collect evidence"})}}]},
    )
    client = RecordingClient([response])
    runner = DeepSeekRunner(config=_config(), http_client=client)

    runner.run(replace(_invocation(), timeout_seconds=3.5))

    assert client.calls[0]["timeout"] == pytest.approx(3.5, abs=0.01)


def test_deepseek_runner_does_not_multiply_invocation_timeout_across_retries(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")

    class ManualClock:
        def __init__(self) -> None:
            self.current = 0.0

        def __call__(self) -> float:
            return self.current

        def advance(self, delta: float) -> None:
            self.current += delta

    class TimeoutingClient:
        def __init__(self, clock: ManualClock) -> None:
            self.clock = clock
            self.calls: list[dict[str, object]] = []

        def post(self, url: str, *, json: dict[str, object], headers: dict[str, str], timeout: float):
            self.calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
            self.clock.advance(timeout)
            raise httpx.ReadTimeout("timed out", request=httpx.Request("POST", url))

    clock = ManualClock()
    client = TimeoutingClient(clock)
    runner = DeepSeekRunner(config=_config(max_retries=2), http_client=client, clock=clock)

    with pytest.raises(ProviderRequestError, match=r"after retries"):
        runner.run(replace(_invocation(), timeout_seconds=3.5))

    assert len(client.calls) == 1
    assert client.calls[0]["timeout"] == 3.5
