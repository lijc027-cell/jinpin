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

    def _get(
        self,
        path: str,
        *,
        params: dict[str, object] | None = None,
        timeout_seconds: float | None = None,
    ) -> httpx.Response:
        headers = {"Accept": "application/vnd.github+json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        url = f"https://api.github.com{path}"
        timeout = self.timeout_seconds if timeout_seconds is None else timeout_seconds
        if self.http_client is None:
            return httpx.get(
                url,
                params=params or {},
                headers=headers,
                timeout=timeout,
                trust_env=False,
            )
        return self.http_client.get(
            url,
            params=params or {},
            headers=headers,
            timeout=timeout,
        )

    def _latest_release(self, repo: str, *, timeout_seconds: float | None = None) -> tuple[str, str]:
        response = self._get(f"/repos/{repo}/releases/latest", timeout_seconds=timeout_seconds)
        if response.status_code == 404:
            return "", ""
        response.raise_for_status()
        payload = response.json()
        return str(payload.get("tag_name", "")), str(payload.get("published_at", ""))

    def _latest_commit_at(
        self,
        repo: str,
        default_branch: str,
        *,
        timeout_seconds: float | None = None,
    ) -> str:
        response = self._get(
            f"/repos/{repo}/commits",
            params={"sha": default_branch, "per_page": 1},
            timeout_seconds=timeout_seconds,
        )
        if response.status_code == 404:
            return ""
        response.raise_for_status()
        payload = response.json()
        if not payload:
            return ""
        latest = payload[0]
        return str(latest.get("commit", {}).get("committer", {}).get("date", ""))

    def lookup(self, query: str, timeout_seconds: float | None = None) -> list[dict[str, str | int]]:
        response = self._get(
            "/search/repositories",
            params={"q": query, "sort": "stars", "order": "desc", "per_page": self.per_page},
            timeout_seconds=timeout_seconds,
        )
        response.raise_for_status()

        payload = response.json()
        repos: list[dict[str, str | int]] = []
        for item in payload.get("items", []):
            repo = str(item.get("full_name", ""))
            stars = int(item.get("stargazers_count", 0))
            default_branch = str(item.get("default_branch", ""))
            latest_release_tag = ""
            latest_release_published_at = ""
            latest_commit_at = ""

            if repo and default_branch:
                try:
                    latest_release_tag, latest_release_published_at = self._latest_release(
                        repo,
                        timeout_seconds=timeout_seconds,
                    )
                except httpx.HTTPError:
                    latest_release_tag, latest_release_published_at = "", ""
                try:
                    latest_commit_at = self._latest_commit_at(
                        repo,
                        default_branch,
                        timeout_seconds=timeout_seconds,
                    )
                except httpx.HTTPError:
                    latest_commit_at = ""

            repos.append(
                {
                    "repo": repo,
                    "stars": stars,
                    "updated_at": str(item.get("updated_at", "")),
                    "forks": int(item.get("forks_count", 0)),
                    "open_issues": int(item.get("open_issues_count", 0)),
                    "default_branch": default_branch,
                    "description": str(item.get("description", "")),
                    "latest_release_tag": latest_release_tag,
                    "latest_release_published_at": latest_release_published_at,
                    "latest_commit_at": latest_commit_at,
                }
            )
        return repos
