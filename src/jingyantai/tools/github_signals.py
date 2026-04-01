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

    def collect(self, query: str, limit: int = 5) -> dict[str, object]:
        headers = {"Accept": "application/vnd.github+json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        params = {"q": query, "sort": "stars", "order": "desc", "per_page": min(limit, self.per_page)}
        url = "https://api.github.com/search/repositories"
        if self.http_client is None:
            response = httpx.get(url, params=params, headers=headers, timeout=self.timeout_seconds)
        else:
            response = self.http_client.get(url, params=params, headers=headers, timeout=self.timeout_seconds)
        response.raise_for_status()

        payload = response.json()
        repos: list[dict[str, object]] = []
        for item in payload.get("items", []):
            stars = int(item.get("stargazers_count", 0))
            repos.append(
                {
                    "full_name": str(item.get("full_name", "")),
                    "html_url": str(item.get("html_url", "")),
                    "description": str(item.get("description") or ""),
                    "stars": stars,
                    "forks": int(item.get("forks_count", 0)),
                    "updated_at": str(item.get("updated_at", "")),
                }
            )
        return {
            "query": query,
            "repo_count": len(repos),
            "total_stars": sum(int(repo["stars"]) for repo in repos),
            "repositories": repos,
        }
