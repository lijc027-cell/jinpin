from __future__ import annotations

from dataclasses import dataclass
import json
import os
from typing import Any

import httpx

from jingyantai.llm.contracts import (
    ModelInvocation,
    ProviderConfig,
    ProviderRequestError,
    ResponseFormatError,
)


@dataclass
class DeepSeekRunner:
    config: ProviderConfig
    http_client: Any | None = None

    def run(self, invocation: ModelInvocation) -> dict[str, Any]:
        url = self.config.base_url.rstrip("/") + "/chat/completions"
        payload = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": invocation.system_prompt},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "schema": invocation.response_schema_name,
                            "payload": invocation.payload,
                            "instructions": "Return JSON only.",
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            "temperature": invocation.temperature,
            "response_format": {"type": "json_object"},
        }

        last_error: Exception | None = None
        for _ in range(self.config.max_retries + 1):
            try:
                api_key = os.getenv(self.config.api_key_env)
                if not api_key:
                    raise ProviderRequestError(f"Missing API key env: {self.config.api_key_env}")

                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                }
                if self.http_client is None:
                    response = httpx.post(
                        url,
                        json=payload,
                        headers=headers,
                        timeout=self.config.timeout_seconds,
                    )
                else:
                    response = self.http_client.post(
                        url,
                        json=payload,
                        headers=headers,
                        timeout=self.config.timeout_seconds,
                    )
                response.raise_for_status()
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                if not isinstance(content, str):
                    raise ResponseFormatError("Model content was not a JSON string")
                parsed = json.loads(content)
                if not isinstance(parsed, dict):
                    raise ResponseFormatError("Model content JSON must decode to an object")
                return parsed
            except ResponseFormatError:
                raise
            except (json.JSONDecodeError, KeyError, TypeError, IndexError) as exc:
                raise ResponseFormatError(f"Failed to parse model response: {exc}") from exc
            except (ProviderRequestError, httpx.HTTPError) as exc:
                last_error = exc

        raise ProviderRequestError(f"DeepSeek request failed after retries: {last_error}") from last_error
