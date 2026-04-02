from __future__ import annotations

from jingyantai.llm.contracts import ModelRunner, ProviderConfig
from jingyantai.llm.deepseek_runner import DeepSeekRunner


def build_model_runner(config: ProviderConfig) -> ModelRunner:
    if config.provider == "deepseek":
        return DeepSeekRunner(config=config)
    raise ValueError(f"Unsupported provider: {config.provider}")
