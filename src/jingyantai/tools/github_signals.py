from __future__ import annotations

import httpx


class GitHubSignals:
    def __init__(
        self,
        token: str | None = None,
        *,
        timeout_seconds: float = 10.0,
        per_page: int = 5,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.token = token
        self.timeout_seconds = timeout_seconds
        self.per_page = per_page
        self.http_client = http_client

    def lookup(self, query: str) -> list[dict[str, str | int]]:
        headers = {"Accept": "application/vnd.github+json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        params = {"q": query, "sort": "stars", "order": "desc", "per_page": self.per_page}
        url = "https://api.github.com/search/repositories"
        if self.http_client is None:
            response = httpx.get(url, params=params, headers=headers, timeout=self.timeout_seconds)
        else:
            response = self.http_client.get(url, params=params, headers=headers, timeout=self.timeout_seconds)
        response.raise_for_status()

        payload = response.json()
        repos: list[dict[str, str | int]] = []
        for item in payload.get("items", []):
            stars = int(item.get("stargazers_count", 0))
            repos.append(
                {
                    "repo": str(item.get("full_name", "")),
                    "stars": stars,
                    "releases": int(item.get("open_issues_count", 0)),
                }
            )
        return repos
