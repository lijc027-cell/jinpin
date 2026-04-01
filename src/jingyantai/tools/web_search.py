from __future__ import annotations

import httpx

from jingyantai.tools.contracts import SearchHit


class TavilySearchClient:
    def __init__(
        self,
        api_key: str,
        *,
        endpoint: str = "https://api.tavily.com/search",
        timeout_seconds: float = 15.0,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.api_key = api_key
        self.endpoint = endpoint
        self.timeout_seconds = timeout_seconds
        self.http_client = http_client

    def search(self, query: str, max_results: int = 5) -> list[SearchHit]:
        payload = {"api_key": self.api_key, "query": query, "max_results": max_results}
        if self.http_client is None:
            response = httpx.post(self.endpoint, json=payload, timeout=self.timeout_seconds)
        else:
            response = self.http_client.post(self.endpoint, json=payload, timeout=self.timeout_seconds)
        response.raise_for_status()

        data = response.json()
        results: list[SearchHit] = []
        for item in data.get("results", []):
            title = str(item.get("title") or "")
            url = str(item.get("url") or "")
            snippet = str(item.get("content") or item.get("snippet") or "")
            if not url:
                continue
            results.append(SearchHit(title=title, url=url, snippet=snippet))
        return results
