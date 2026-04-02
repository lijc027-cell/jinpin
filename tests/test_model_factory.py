from __future__ import annotations

import inspect

import pytest

from jingyantai.llm.contracts import (
    ModelInvocation,
    ModelRunner,
    ModelRunnerError,
    ProviderConfig,
    ProviderRequestError,
    ResponseFormatError,
)
from jingyantai.llm.deepseek_runner import DeepSeekRunner
from jingyantai.llm.factory import build_model_runner


def test_provider_config_fields_are_available():
    config = ProviderConfig(
        provider="deepseek",
        model="deepseek-chat",
        base_url="https://api.deepseek.com",
        api_key_env="DEEPSEEK_API_KEY",
        timeout_seconds=30.0,
        max_retries=2,
    )

    assert config.provider == "deepseek"
    assert config.model == "deepseek-chat"
    assert config.base_url == "https://api.deepseek.com"
    assert config.api_key_env == "DEEPSEEK_API_KEY"
    assert config.timeout_seconds == 30.0
    assert config.max_retries == 2


def test_provider_config_defaults_match_task_1_plan():
    config = ProviderConfig(
        provider="deepseek",
        model="deepseek-chat",
        base_url="https://api.deepseek.com",
        api_key_env="DEEPSEEK_API_KEY",
    )

    assert config.timeout_seconds == 20.0
    assert config.max_retries == 1


def test_model_invocation_fields_are_available_with_default_temperature():
    invocation = ModelInvocation(
        system_prompt="you are helpful",
        payload={"question": "hello"},
        response_schema_name="summary",
    )

    assert invocation.system_prompt == "you are helpful"
    assert invocation.payload == {"question": "hello"}
    assert invocation.response_schema_name == "summary"
    assert invocation.temperature == 0.0


def test_model_runner_errors_follow_contract_hierarchy():
    assert issubclass(ProviderRequestError, ModelRunnerError)
    assert issubclass(ResponseFormatError, ModelRunnerError)


def test_model_runner_protocol_exposes_config_and_run():
    run_sig = inspect.signature(ModelRunner.run)
    assert list(run_sig.parameters.keys()) == ["self", "invocation"]
    assert "config" in ModelRunner.__annotations__


def test_build_model_runner_returns_deepseek_runner_for_deepseek_provider():
    config = ProviderConfig(
        provider="deepseek",
        model="deepseek-chat",
        base_url="https://api.deepseek.com",
        api_key_env="DEEPSEEK_API_KEY",
        timeout_seconds=30.0,
        max_retries=2,
    )

    runner = build_model_runner(config)

    assert isinstance(runner, DeepSeekRunner)
    assert runner.config == config


def test_build_model_runner_raises_for_unknown_provider():
    config = ProviderConfig(
        provider="unknown-provider",
        model="model-x",
        base_url="https://example.com",
        api_key_env="API_KEY",
        timeout_seconds=30.0,
        max_retries=1,
    )

    with pytest.raises(ValueError, match=r"^Unsupported provider: unknown-provider$"):
        build_model_runner(config)
