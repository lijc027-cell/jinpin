from __future__ import annotations

from urllib.parse import urlparse

from jingyantai.tools.contracts import GitHubSignalsClient, PageExtractor, SearchClient


class ResearchTools:
    def __init__(self, search_client: SearchClient, page_extractor: PageExtractor, github_signals_client: GitHubSignalsClient) -> None:
        self.search_client = search_client
        self.page_extractor = page_extractor
        self.github_signals_client = github_signals_client

    def search_competitor_candidates(self, target: str, product_type: str, max_results: int = 5) -> list[dict[str, str]]:
        query = f"{target} {product_type} competitors alternatives"
        hits = self.search_client.search(query=query, max_results=max_results)
        candidates: list[dict[str, str]] = []
        for index, hit in enumerate(hits, start=1):
            domain = urlparse(hit.url).netloc.removeprefix("www.")
            candidates.append(
                {
                    "candidate_id": f"cand-{index}",
                    "name": hit.title or domain or f"candidate-{index}",
                    "canonical_url": hit.url,
                    "why_candidate": hit.snippet,
                    "source": "web_search",
                    "domain": domain,
                }
            )
        return candidates

    def collect_positioning_evidence(self, subject: str, url: str) -> dict[str, str]:
        page = self.page_extractor.extract(url)
        return {
            "subject": subject,
            "dimension": "positioning",
            "source_url": url,
            "summary": page.text[:600],
            "page_title": page.title,
            "page_excerpt": page.excerpt,
        }

    def collect_workflow_evidence(self, subject: str, url: str) -> dict[str, str]:
        page = self.page_extractor.extract(url)
        return {
            "subject": subject,
            "dimension": "workflow",
            "source_url": url,
            "summary": page.text[:600],
            "page_title": page.title,
            "page_excerpt": page.excerpt,
        }

    def collect_pricing_access_evidence(self, subject: str, url: str) -> dict[str, str]:
        page = self.page_extractor.extract(url)
        return {
            "subject": subject,
            "dimension": "pricing_access",
            "source_url": url,
            "summary": page.text[:600],
            "page_title": page.title,
            "page_excerpt": page.excerpt,
        }

    def collect_github_ecosystem_signals(self, subject: str, limit: int = 5) -> dict[str, object]:
        return self.github_signals_client.collect(query=subject, limit=limit)

    def collect_market_heat_signals(self, topic: str, max_results: int = 3) -> dict[str, object]:
        search_hits = self.search_client.search(query=topic, max_results=max_results)
        web_signals: list[dict[str, str]] = []
        for hit in search_hits:
            page = self.page_extractor.extract(hit.url)
            web_signals.append(
                {
                    "source_url": hit.url,
                    "title": hit.title,
                    "snippet": hit.snippet,
                    "page_title": page.title,
                    "page_excerpt": page.excerpt,
                }
            )

        github_signals = self.collect_github_ecosystem_signals(topic, limit=max_results)
        signal_count = len(web_signals) + int(github_signals.get("repo_count", 0))
        summary = search_hits[0].snippet if search_hits else f"No web signals for {topic}"
        return {
            "topic": topic,
            "summary": summary,
            "web_signals": web_signals,
            "github_signals": github_signals,
            "signal_count": signal_count,
        }

    def build_evidence_bundle(self, subject: str, url: str) -> dict[str, object]:
        return {
            "positioning": self.collect_positioning_evidence(subject=subject, url=url),
            "workflow": self.collect_workflow_evidence(subject=subject, url=url),
            "pricing_access": self.collect_pricing_access_evidence(subject=subject, url=url),
            "github_ecosystem": self.collect_github_ecosystem_signals(subject=subject),
            "market_heat": self.collect_market_heat_signals(topic=subject),
        }
