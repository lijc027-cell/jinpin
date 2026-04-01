from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


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


class SearchClient(Protocol):
    def search(self, query: str, max_results: int = 5) -> list[SearchHit]: ...


class PageExtractor(Protocol):
    def extract(self, url: str) -> PageData: ...


class GitHubSignalsClient(Protocol):
    def collect(self, query: str, limit: int = 5) -> dict[str, object]: ...
