from __future__ import annotations

from dataclasses import dataclass
import json
import os
from time import perf_counter
from typing import Any, Callable

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
    clock: Callable[[], float] = perf_counter

    def run(self, invocation: ModelInvocation) -> dict[str, Any]:
        url = self.config.base_url.rstrip("/") + "/chat/completions"
        timeout = self.config.timeout_seconds if invocation.timeout_seconds is None else invocation.timeout_seconds
        deadline_at = None if invocation.timeout_seconds is None else self.clock() + timeout
        payload = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": invocation.system_prompt},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "schema": invocation.response_schema_name,
                            "response_schema": invocation.response_schema,
                            "payload": invocation.payload,
                            "instructions": "Return JSON only. Do not wrap the answer in schema or payload fields.",
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
            attempt_timeout = timeout
            if deadline_at is not None:
                remaining_timeout = deadline_at - self.clock()
                if remaining_timeout <= 0:
                    last_error = ProviderRequestError("Invocation timeout budget exhausted before retry")
                    break
                attempt_timeout = min(timeout, remaining_timeout)
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
                        timeout=attempt_timeout,
                        trust_env=False,
                    )
                else:
                    response = self.http_client.post(
                        url,
                        json=payload,
                        headers=headers,
                        timeout=attempt_timeout,
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
                if deadline_at is not None and deadline_at - self.clock() <= 0:
                    break

        raise ProviderRequestError(f"DeepSeek request failed after retries: {last_error}") from last_error
