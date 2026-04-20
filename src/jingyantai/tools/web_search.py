from __future__ import annotations

import httpx

from jingyantai.tools.contracts import SearchHit


class ExaSearchClient:
    def __init__(
        self,
        api_key: str,
        *,
        endpoint: str = "https://api.exa.ai/search",
        timeout_seconds: float = 15.0,
        http_client: httpx.Client | None = None,
        max_retries: int = 1,
    ) -> None:
        self.api_key = api_key
        self.endpoint = endpoint
        self.timeout_seconds = timeout_seconds
        self.http_client = http_client
        self.max_retries = max_retries

    def _snippet_from_result(self, item: dict[str, object]) -> str:
        highlights = item.get("highlights")
        if isinstance(highlights, list):
            for entry in highlights:
                if isinstance(entry, str) and entry:
                    return entry

        summary = item.get("summary")
        if isinstance(summary, str) and summary:
            return summary

        text = item.get("text")
        if isinstance(text, str) and text:
            return text[:300]

        return ""

    def search(
        self,
        query: str,
        max_results: int = 5,
        timeout_seconds: float | None = None,
    ) -> list[SearchHit]:
        headers = {"x-api-key": self.api_key, "Content-Type": "application/json"}
        payload = {
            "query": query,
            "type": "auto",
            "numResults": max_results,
            "contents": {"highlights": {"numSentences": 2}},
        }
        timeout = self.timeout_seconds if timeout_seconds is None else timeout_seconds

        last_error: Exception | None = None
        for _ in range(self.max_retries + 1):
            try:
                if self.http_client is None:
                    response = httpx.post(
                        self.endpoint,
                        json=payload,
                        headers=headers,
                        timeout=timeout,
                        trust_env=False,
                    )
                else:
                    response = self.http_client.post(
                        self.endpoint,
                        json=payload,
                        headers=headers,
                        timeout=timeout,
                    )
                response.raise_for_status()
                break
            except httpx.HTTPError as exc:
                last_error = exc
        else:
            raise last_error if last_error is not None else RuntimeError("Exa search failed without an HTTP error")

        data = response.json()
        results: list[SearchHit] = []
        for item in data.get("results", []):
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "")
            url = str(item.get("url") or "")
            snippet = self._snippet_from_result(item)
            if not url:
                continue
            results.append(SearchHit(title=title, url=url, snippet=snippet))
        return results
