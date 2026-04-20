from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class SearchHit:
    title: str
    url: str
    snippet: str


@dataclass(frozen=True)
class PageData:
    url: str
    title: str
    text: str
    excerpt: str


@dataclass
class ToolExecutionMetrics:
    external_fetches: int = 0
    fetch_breakdown: dict[str, int] = field(default_factory=dict)
    timings_ms: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


class SearchClient(Protocol):
    def search(self, query: str, max_results: int = 5) -> list[SearchHit]: ...


class PageExtractor(Protocol):
    def extract(self, url: str) -> PageData: ...


class GitHubSignalsClient(Protocol):
    def lookup(self, query: str) -> list[dict[str, str | int]]: ...


@runtime_checkable
class ResearchToolset(Protocol):
    def search_competitor_candidates(
        self,
        target: str,
        hypothesis: str,
        source_mix: list[str],
        max_results: int = 5,
    ) -> list[dict[str, str]]: ...

    def collect_positioning_evidence(self, subject: str, url: str) -> dict[str, str]: ...

    def collect_workflow_evidence(self, subject: str, url: str) -> dict[str, str]: ...

    def collect_pricing_access_evidence(self, subject: str, url: str) -> dict[str, str]: ...

    def collect_github_ecosystem_signals(self, subject: str) -> list[dict[str, str | int]]: ...

    def collect_market_heat_signals(self, subject: str, max_results: int = 3) -> dict[str, object]: ...

    def build_evidence_bundle(self, subject: str, url: str) -> dict[str, object]: ...
