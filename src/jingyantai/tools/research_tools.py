from __future__ import annotations

import re
from urllib.parse import urlparse

from jingyantai.tools.contracts import GitHubSignalsClient, PageData, PageExtractor, ResearchToolset, SearchClient


class ResearchTools(ResearchToolset):
    def __init__(self, search_client: SearchClient, page_extractor: PageExtractor, github_signals: GitHubSignalsClient) -> None:
        self.search_client = search_client
        self.page_extractor = page_extractor
        self.github_signals = github_signals

    def search_competitor_candidates(
        self,
        target: str,
        hypothesis: str,
        source_mix: list[str],
        max_results: int = 5,
    ) -> list[dict[str, str]]:
        candidates: list[dict[str, str]] = []
        source_set = set(source_mix)
        seen_urls: set[str] = set()
        seen_identities: set[str] = set()

        if "web" in source_set:
            query = f"{target} competitor {hypothesis}"
            hits = self.search_client.search(query=query, max_results=max_results)
            for hit in hits:
                normalized_url = hit.url.lower().rstrip("/")
                if normalized_url in seen_urls:
                    continue
                seen_urls.add(normalized_url)
                domain = urlparse(hit.url).netloc.removeprefix("www.")
                domain_root = domain.split(".")[0].lower()
                if domain_root:
                    seen_identities.add(domain_root)
                candidates.append(
                    {
                        "candidate_id": "",
                        "name": hit.title or domain or "candidate",
                        "canonical_url": hit.url,
                        "why_candidate": hit.snippet,
                        "source": "web",
                        "domain": domain,
                    }
                )

        if "github" in source_set:
            query = f"{target} {hypothesis}"
            github_hits = self.github_signals.lookup(query=query)
            for hit in github_hits[:max_results]:
                repo = str(hit.get("repo", ""))
                if not repo:
                    continue
                url = f"https://github.com/{repo}"
                normalized_url = url.lower().rstrip("/")
                if normalized_url in seen_urls:
                    continue
                repo_tokens = {token for token in re.split(r"[/_.-]+", repo.lower()) if token}
                if repo_tokens & seen_identities:
                    continue
                seen_urls.add(normalized_url)
                seen_identities.update(repo_tokens)
                candidates.append(
                    {
                        "candidate_id": "",
                        "name": repo,
                        "canonical_url": url,
                        "why_candidate": f"GitHub stars: {hit.get('stars', 0)}",
                        "source": "github",
                        "domain": "github.com",
                    }
                )

        for index, candidate in enumerate(candidates, start=1):
            candidate["candidate_id"] = f"cand-{index}"
        return candidates

    def _evidence_from_page(self, subject: str, page: PageData, dimension: str) -> dict[str, str]:
        return {
            "subject": subject,
            "dimension": dimension,
            "source_url": page.url,
            "summary": page.text[:600],
            "page_title": page.title,
            "page_excerpt": page.excerpt,
        }

    def collect_positioning_evidence(self, subject: str, url: str) -> dict[str, str]:
        page = self.page_extractor.extract(url)
        return self._evidence_from_page(subject=subject, page=page, dimension="positioning")

    def collect_workflow_evidence(self, subject: str, url: str) -> dict[str, str]:
        page = self.page_extractor.extract(url)
        return self._evidence_from_page(subject=subject, page=page, dimension="workflow")

    def collect_pricing_access_evidence(self, subject: str, url: str) -> dict[str, str]:
        page = self.page_extractor.extract(url)
        return self._evidence_from_page(subject=subject, page=page, dimension="pricing or access")

    def collect_github_ecosystem_signals(self, subject: str) -> list[dict[str, str | int]]:
        return self.github_signals.lookup(query=subject)

    def collect_market_heat_signals(self, subject: str, max_results: int = 3) -> dict[str, object]:
        search_hits = self.search_client.search(query=subject, max_results=max_results)
        search = [
            {"title": hit.title, "url": hit.url, "snippet": hit.snippet}
            for hit in search_hits
        ]
        web_signals: list[dict[str, str]] = []
        for hit in search_hits:
            page = self.page_extractor.extract(hit.url)
            web_signals.append(
                {
                    "source_url": page.url,
                    "title": hit.title,
                    "snippet": hit.snippet,
                    "page_title": page.title,
                    "page_excerpt": page.excerpt,
                }
            )

        github = self.collect_github_ecosystem_signals(subject)
        signal_count = len(web_signals) + len(github)
        summary = f"{subject}: {search_hits[0].snippet}" if search_hits else f"{subject} has no search summary."
        return {
            "subject": subject,
            "summary": summary,
            "search": search,
            "web_signals": web_signals,
            "github": github,
            "signal_count": signal_count,
        }

    def build_evidence_bundle(self, subject: str, url: str) -> dict[str, object]:
        page = self.page_extractor.extract(url)
        return {
            "positioning": self._evidence_from_page(subject=subject, page=page, dimension="positioning"),
            "workflow": self._evidence_from_page(subject=subject, page=page, dimension="workflow"),
            "pricing_or_access": self._evidence_from_page(subject=subject, page=page, dimension="pricing or access"),
            "github": self.collect_github_ecosystem_signals(subject=subject),
            "heat": self.collect_market_heat_signals(subject=subject),
        }
