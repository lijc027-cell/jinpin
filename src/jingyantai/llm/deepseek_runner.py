from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from jingyantai.llm.contracts import ModelInvocation, ProviderConfig


@dataclass
class DeepSeekRunner:
    config: ProviderConfig

    def run(self, invocation: ModelInvocation) -> dict[str, Any]:
        raise NotImplementedError("DeepSeekRunner.run is not implemented yet")
