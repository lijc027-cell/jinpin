import inspect

import httpx

from jingyantai.tools.contracts import PageData, ResearchToolset, SearchHit
from jingyantai.tools.github_signals import GitHubSignals
from jingyantai.tools.page_extract import HttpPageExtractor
from jingyantai.tools.research_tools import ResearchTools
from jingyantai.tools.web_search import ExaSearchClient


class FakeSearchClient:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def search(self, query: str, max_results: int = 5) -> list[SearchHit]:
        self.queries.append(query)
        return [
            SearchHit(
                title="Codeium - AI coding assistant alternatives",
                url="https://codeium.com",
                snippet="Codeium is an AI coding assistant for developers.",
            ),
            SearchHit(
                title="Cursor - AI-first editor",
                url="https://cursor.com",
                snippet="Cursor provides coding workflows with AI features.",
            ),
        ][:max_results]


class EmptySearchClient:
    def search(self, query: str, max_results: int = 5) -> list[SearchHit]:
        return []


class FailingSearchClient:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def search(self, query: str, max_results: int = 5) -> list[SearchHit]:
        self.queries.append(query)
        raise RuntimeError("search unavailable")


class FakePageExtractor:
    def __init__(self) -> None:
        self.calls = 0

    def extract(self, url: str) -> PageData:
        self.calls += 1
        return PageData(
            url=f"{url.rstrip('/')}/landing",
            title="Market Traction Update",
            text="Weekly active developers grew quickly in Q1.",
            excerpt="Weekly active developers grew quickly in Q1.",
        )


class FakeGitHubSignalsClient:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def lookup(self, query: str) -> list[dict[str, str | int]]:
        self.queries.append(query)
        return [
            {"repo": "acme/agent-kit", "stars": 900, "updated_at": "2026-03-31T00:00:00Z"},
            {"repo": "codeium/codeium", "stars": 2000, "updated_at": "2026-03-30T00:00:00Z"},
        ]


def test_search_competitor_candidates_returns_structured_candidates():
    search = FakeSearchClient()
    github = FakeGitHubSignalsClient()
    tools = ResearchTools(
        search_client=search,
        page_extractor=FakePageExtractor(),
        github_signals=github,
    )

    candidates = tools.search_competitor_candidates(
        target="Claude Code",
        hypothesis="coding agent",
        source_mix=["web", "github"],
        max_results=2,
    )

    assert len(candidates) == 3
    first = candidates[0]
    assert set(first.keys()) >= {
        "candidate_id",
        "name",
        "canonical_url",
        "why_candidate",
        "source",
        "domain",
    }
    assert first["candidate_id"].startswith("cand-")
    assert first["canonical_url"] == "https://codeium.com"
    assert first["source"] == "web"
    assert candidates[-1]["source"] == "github"
    assert candidates[-1]["canonical_url"] == "https://github.com/acme/agent-kit"
    assert "Claude Code competitor coding agent" in search.queries[0]
    assert github.queries[0] == "Claude Code coding agent"


def test_search_competitor_candidates_respects_source_mix():
    search = FakeSearchClient()
    github = FakeGitHubSignalsClient()
    tools = ResearchTools(
        search_client=search,
        page_extractor=FakePageExtractor(),
        github_signals=github,
    )

    web_only = tools.search_competitor_candidates(
        target="Claude Code",
        hypothesis="coding agent",
        source_mix=["web"],
        max_results=2,
    )
    github_only = tools.search_competitor_candidates(
        target="Claude Code",
        hypothesis="coding agent",
        source_mix=["github"],
        max_results=2,
    )

    assert {item["source"] for item in web_only} == {"web"}
    assert {item["source"] for item in github_only} == {"github"}
    assert len(search.queries) >= 1
    assert len(github.queries) >= 1


def test_search_competitor_candidates_falls_back_to_github_when_web_search_fails():
    github = FakeGitHubSignalsClient()
    tools = ResearchTools(
        search_client=FailingSearchClient(),
        page_extractor=FakePageExtractor(),
        github_signals=github,
    )

    candidates = tools.search_competitor_candidates(
        target="Claude Code",
        hypothesis="coding agent",
        source_mix=["web", "github"],
        max_results=2,
    )
    metrics = tools.consume_last_metrics()

    assert {item["source"] for item in candidates} == {"github"}
    assert len(candidates) == 2
    assert github.queries == ["Claude Code coding agent"]
    assert any("web search failed" in note for note in metrics.notes)


def test_search_competitor_candidates_skips_late_fetches_after_runtime_deadline_expires():
    class ManualClock:
        def __init__(self) -> None:
            self.current = 0.0

        def __call__(self) -> float:
            return self.current

        def advance(self, delta: float) -> None:
            self.current += delta

    class SearchClient:
        def __init__(self, clock: ManualClock) -> None:
            self.clock = clock
            self.calls = 0
            self.timeouts: list[float | None] = []

        def search(self, query: str, max_results: int = 5, timeout_seconds: float | None = None) -> list[SearchHit]:
            self.calls += 1
            self.timeouts.append(timeout_seconds)
            self.clock.advance(0.01)
            return [SearchHit(title="OpenCode", url="https://opencode.dev", snippet="terminal coding agent")]

    class PageExtractor:
        def __init__(self, clock: ManualClock) -> None:
            self.clock = clock
            self.calls = 0
            self.timeouts: list[float | None] = []

        def extract(self, url: str, timeout_seconds: float | None = None) -> PageData:
            self.calls += 1
            self.timeouts.append(timeout_seconds)
            if timeout_seconds is not None:
                self.clock.advance(timeout_seconds)
                raise TimeoutError(f"page extract timed out after {timeout_seconds:.3f}s")
            raise AssertionError("expected runtime deadline timeout override")

    class GitHubSignalsClient:
        def __init__(self) -> None:
            self.calls = 0
            self.timeouts: list[float | None] = []

        def lookup(self, query: str, timeout_seconds: float | None = None) -> list[dict[str, str | int]]:
            self.calls += 1
            self.timeouts.append(timeout_seconds)
            return []

    clock = ManualClock()
    search = SearchClient(clock)
    page = PageExtractor(clock)
    github = GitHubSignalsClient()
    tools = ResearchTools(search_client=search, page_extractor=page, github_signals=github, clock=clock)
    tools.set_runtime_deadline(0.015)

    candidates = tools.search_competitor_candidates(
        target="Claude Code",
        hypothesis="terminal coding agent",
        source_mix=["web", "github"],
        max_results=5,
    )
    metrics = tools.consume_last_metrics()

    assert len(candidates) == 1
    assert search.calls == 1
    assert search.timeouts == [0.015]
    assert page.calls == 1
    assert page.timeouts and page.timeouts[0] is not None and page.timeouts[0] <= 0.0051
    assert github.calls == 0
    assert metrics.external_fetches == 2
    assert metrics.fetch_breakdown == {"search": 1, "page_extract": 1}
    assert any("phase runtime deadline exceeded before external fetch" in note for note in metrics.notes)


def test_collect_market_heat_signals_merges_search_page_and_github_signals():
    page = FakePageExtractor()
    tools = ResearchTools(
        search_client=FakeSearchClient(),
        page_extractor=page,
        github_signals=FakeGitHubSignalsClient(),
    )

    signals = tools.collect_market_heat_signals(subject="coding agent", max_results=1)

    assert signals["summary"].startswith("coding agent")
    assert len(signals["search"]) == 1
    assert signals["search"][0]["url"] == "https://codeium.com"
    assert len(signals["web_signals"]) == 1
    assert signals["web_signals"][0]["source_url"] == "https://codeium.com/landing"
    assert signals["web_signals"][0]["page_excerpt"] == "Weekly active developers grew quickly in Q1."
    assert signals["github"][0]["updated_at"] == "2026-03-31T00:00:00Z"
    assert signals["signal_count"] == 3
    assert page.calls == 1


def test_collect_github_ecosystem_signals_returns_lookup_list():
    tools = ResearchTools(
        search_client=FakeSearchClient(),
        page_extractor=FakePageExtractor(),
        github_signals=FakeGitHubSignalsClient(),
    )

    github = tools.collect_github_ecosystem_signals(subject="Aider")

    assert isinstance(github, list)
    assert github[0]["repo"] == "acme/agent-kit"
    assert "updated_at" in github[0]


class TrackingPageExtractor(FakePageExtractor):
    def __init__(self) -> None:
        super().__init__()
        self.urls: list[str] = []

    def extract(self, url: str) -> PageData:
        self.urls.append(url)
        return super().extract(url)


class PartiallyFailingPageExtractor(FakePageExtractor):
    def __init__(self, failing_url: str) -> None:
        super().__init__()
        self.failing_url = failing_url

    def extract(self, url: str) -> PageData:
        if url == self.failing_url:
            raise RuntimeError("temporary extraction failure")
        return super().extract(url)


class PrimaryUrlFailingPageExtractor(FakePageExtractor):
    def __init__(self, failing_url: str) -> None:
        super().__init__()
        self.failing_url = failing_url

    def extract(self, url: str) -> PageData:
        if url == self.failing_url:
            raise RuntimeError("primary candidate url unreachable")
        return super().extract(url)


class TrackingPrimaryUrlFailingPageExtractor(FakePageExtractor):
    def __init__(self, failing_url: str) -> None:
        super().__init__()
        self.failing_url = failing_url
        self.urls: list[str] = []
        self.timeouts: list[float | None] = []

    def extract(self, url: str, timeout_seconds: float | None = None) -> PageData:
        self.urls.append(url)
        self.timeouts.append(timeout_seconds)
        if url == self.failing_url:
            raise RuntimeError("primary candidate url unreachable")
        return super().extract(url)


class TrackingPrimaryUrlTimeoutPageExtractor(FakePageExtractor):
    def __init__(self, failing_url: str) -> None:
        super().__init__()
        self.failing_url = failing_url
        self.urls: list[str] = []
        self.timeouts: list[float | None] = []

    def extract(self, url: str, timeout_seconds: float | None = None) -> PageData:
        self.urls.append(url)
        self.timeouts.append(timeout_seconds)
        if url == self.failing_url:
            raise TimeoutError("timed out")
        return super().extract(url)


def test_build_evidence_bundle_fetches_main_url_once_but_allows_heat_pages():
    page = TrackingPageExtractor()
    tools = ResearchTools(
        search_client=FakeSearchClient(),
        page_extractor=page,
        github_signals=FakeGitHubSignalsClient(),
    )

    bundle = tools.build_evidence_bundle(subject="Aider", url="https://aider.chat")

    assert set(bundle.keys()) == {"positioning", "workflow", "pricing_or_access", "github", "heat", "diagnostics"}
    assert bundle["pricing_or_access"]["dimension"] == "pricing or access"
    assert bundle["positioning"]["source_url"] == "https://aider.chat/landing"
    assert bundle["workflow"]["source_url"] == "https://aider.chat/landing"
    assert bundle["pricing_or_access"]["source_url"] == "https://aider.chat/landing"
    assert page.urls.count("https://aider.chat") == 1
    assert "https://codeium.com" in page.urls


def test_build_evidence_bundle_reuses_cached_search_page_and_github_results():
    search = FakeSearchClient()
    github = FakeGitHubSignalsClient()
    page = TrackingPageExtractor()
    tools = ResearchTools(
        search_client=search,
        page_extractor=page,
        github_signals=github,
    )

    first = tools.build_evidence_bundle(subject="Aider", url="https://aider.chat")
    first_metrics = tools.consume_last_metrics()
    second = tools.build_evidence_bundle(subject="Aider", url="https://aider.chat")
    second_metrics = tools.consume_last_metrics()

    assert first["positioning"]["source_url"] == second["positioning"]["source_url"]
    assert search.queries == ["Aider"]
    assert github.queries == ["Aider"]
    assert page.calls == 3
    assert first_metrics.external_fetches == 5
    assert second_metrics.external_fetches == 0


def test_build_evidence_bundle_reuses_cached_failed_primary_page_extract_across_repeated_calls():
    page = TrackingPrimaryUrlFailingPageExtractor("https://broken.example/product")
    tools = ResearchTools(
        search_client=FakeSearchClient(),
        page_extractor=page,
        github_signals=FakeGitHubSignalsClient(),
    )

    first = tools.build_evidence_bundle(subject="Aider", url="https://broken.example/product")
    first_metrics = tools.consume_last_metrics()
    second = tools.build_evidence_bundle(subject="Aider", url="https://broken.example/product")
    second_metrics = tools.consume_last_metrics()

    assert first["diagnostics"]["resolved_via"] == "search_hit"
    assert second["diagnostics"]["resolved_via"] == "search_hit"
    assert page.urls.count("https://broken.example/product") == 1
    assert first_metrics.external_fetches == 5
    assert second_metrics.external_fetches == 0


def test_build_evidence_bundle_reuses_cached_timeout_fallback_across_repeated_calls():
    page = TrackingPrimaryUrlTimeoutPageExtractor("https://slow.example/product")
    tools = ResearchTools(
        search_client=FakeSearchClient(),
        page_extractor=page,
        github_signals=FakeGitHubSignalsClient(),
    )

    first = tools.build_evidence_bundle(subject="Aider", url="https://slow.example/product")
    first_metrics = tools.consume_last_metrics()
    second = tools.build_evidence_bundle(subject="Aider", url="https://slow.example/product")
    second_metrics = tools.consume_last_metrics()

    assert first["diagnostics"]["resolved_via"] == "search_hit"
    assert second["diagnostics"]["resolved_via"] == "search_hit"
    assert page.urls.count("https://slow.example/product") == 1
    assert first_metrics.external_fetches == 5
    assert second_metrics.external_fetches == 0


def test_search_competitor_candidates_caps_page_extract_timeout_for_url_precheck():
    class SearchClient:
        def search(self, query: str, max_results: int = 5) -> list[SearchHit]:
            return [
                SearchHit(
                    title="Example Docs",
                    url="https://example.dev/docs",
                    snippet="Docs page.",
                )
            ]

    class PageExtractor:
        def __init__(self) -> None:
            self.timeouts: list[float | None] = []

        def extract(self, url: str, timeout_seconds: float | None = None) -> PageData:
            self.timeouts.append(timeout_seconds)
            return PageData(url=url, title=url, text="text", excerpt="excerpt")

    page = PageExtractor()
    tools = ResearchTools(
        search_client=SearchClient(),
        page_extractor=page,
        github_signals=FakeGitHubSignalsClient(),
    )

    tools.search_competitor_candidates(
        target="Claude Code",
        hypothesis="coding agent",
        source_mix=["web"],
        max_results=1,
    )

    assert page.timeouts == [3.0]


def test_collect_market_heat_signals_tolerates_single_page_extract_failure():
    tools = ResearchTools(
        search_client=FakeSearchClient(),
        page_extractor=PartiallyFailingPageExtractor("https://cursor.com"),
        github_signals=FakeGitHubSignalsClient(),
    )

    heat = tools.collect_market_heat_signals(subject="coding agent", max_results=2)

    assert "summary" in heat
    assert len(heat["search"]) == 2
    assert len(heat["github"]) == 2
    assert len(heat["web_signals"]) == 2
    failed_signal = next(signal for signal in heat["web_signals"] if signal["title"].startswith("Cursor"))
    assert failed_signal["source_url"] == "https://cursor.com"
    assert failed_signal["page_excerpt"] == "page extraction unavailable"


def test_build_evidence_bundle_survives_heat_extract_failure():
    tools = ResearchTools(
        search_client=FakeSearchClient(),
        page_extractor=PartiallyFailingPageExtractor("https://cursor.com"),
        github_signals=FakeGitHubSignalsClient(),
    )

    bundle = tools.build_evidence_bundle(subject="Aider", url="https://aider.chat")

    assert set(bundle.keys()) == {"positioning", "workflow", "pricing_or_access", "github", "heat", "diagnostics"}
    assert "summary" in bundle["heat"]
    assert len(bundle["heat"]["search"]) == 2


def test_build_evidence_bundle_survives_search_failure_when_primary_page_is_available():
    tools = ResearchTools(
        search_client=FailingSearchClient(),
        page_extractor=FakePageExtractor(),
        github_signals=FakeGitHubSignalsClient(),
    )

    bundle = tools.build_evidence_bundle(subject="Aider", url="https://aider.chat")
    metrics = tools.consume_last_metrics()

    assert bundle["positioning"]["source_url"] == "https://aider.chat/landing"
    assert bundle["heat"]["search"] == []
    assert bundle["heat"]["summary"] == "Aider has no search summary."
    assert len(bundle["github"]) == 2
    assert any("subject search failed" in note for note in metrics.notes)


def test_build_evidence_bundle_falls_back_to_search_hit_when_primary_url_is_unreachable():
    tools = ResearchTools(
        search_client=FakeSearchClient(),
        page_extractor=PrimaryUrlFailingPageExtractor("https://broken.example/product"),
        github_signals=FakeGitHubSignalsClient(),
    )

    bundle = tools.build_evidence_bundle(subject="Aider", url="https://broken.example/product")

    assert bundle["positioning"]["source_url"] == "https://codeium.com/landing"
    assert bundle["workflow"]["source_url"] == "https://codeium.com/landing"
    assert bundle["pricing_or_access"]["source_url"] == "https://codeium.com/landing"
    assert bundle["heat"]["search"][0]["url"] == "https://codeium.com"


def test_build_evidence_bundle_exposes_diagnostics_and_consumable_tool_metrics():
    tools = ResearchTools(
        search_client=FakeSearchClient(),
        page_extractor=PrimaryUrlFailingPageExtractor("https://broken.example/product"),
        github_signals=FakeGitHubSignalsClient(),
    )

    bundle = tools.build_evidence_bundle(subject="Aider", url="https://broken.example/product")
    metrics = tools.consume_last_metrics()

    assert bundle["diagnostics"]["requested_url"] == "https://broken.example/product"
    assert bundle["diagnostics"]["resolved_via"] == "search_hit"
    assert bundle["diagnostics"]["resolved_url"] == "https://codeium.com/landing"
    assert "primary candidate url unreachable" in bundle["diagnostics"]["fallback_reason"]
    assert metrics.external_fetches == 5
    assert set(metrics.timings_ms) == {"search", "page_extract", "github_lookup"}
    assert any("fallback to search hit" in note for note in metrics.notes)


def test_build_evidence_bundle_prefers_dimension_specific_pages_when_search_hits_exist():
    class SearchClient:
        def search(self, query: str, max_results: int = 5) -> list[SearchHit]:
            if query == "Aider":
                return [
                    SearchHit(title="Aider", url="https://aider.chat", snippet="Official site."),
                    SearchHit(title="Aider Docs", url="https://aider.chat/docs", snippet="Docs."),
                    SearchHit(title="Aider Pricing", url="https://aider.chat/pricing", snippet="Pricing."),
                ]
            return []

    class Extractor:
        def extract(self, url: str) -> PageData:
            return PageData(url=url, title=url, text=f"text for {url}", excerpt=f"excerpt for {url}")

    tools = ResearchTools(
        search_client=SearchClient(),
        page_extractor=Extractor(),
        github_signals=FakeGitHubSignalsClient(),
    )

    bundle = tools.build_evidence_bundle(subject="Aider", url="https://aider.chat")

    assert bundle["positioning"]["source_url"] == "https://aider.chat"
    assert bundle["workflow"]["source_url"] == "https://aider.chat/docs"
    assert bundle["pricing_or_access"]["source_url"] == "https://aider.chat/pricing"
    assert bundle["diagnostics"]["dimension_sources"] == {
        "positioning": "primary_url",
        "workflow": "workflow_search_hit",
        "pricing_or_access": "pricing_search_hit",
    }


class GithubFocusedFallbackSearchClient:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def search(self, query: str, max_results: int = 5) -> list[SearchHit]:
        self.queries.append(query)
        if query == "OpenAI Codex":
            return [
                SearchHit(
                    title="OpenAI Codex",
                    url="https://openai.com/index/codex/",
                    snippet="Official page.",
                )
            ]
        if query == "OpenAI Codex github":
            return [
                SearchHit(
                    title="openai/codex",
                    url="https://github.com/openai/codex",
                    snippet="Lightweight coding agent that runs in your terminal.",
                )
            ]
        return []


class MultiUrlFailingPageExtractor(FakePageExtractor):
    def __init__(self, failing_urls: set[str]) -> None:
        super().__init__()
        self.failing_urls = failing_urls

    def extract(self, url: str) -> PageData:
        if url in self.failing_urls:
            raise RuntimeError(f"page blocked: {url}")
        return super().extract(url)


def test_build_evidence_bundle_falls_back_to_github_focused_search_when_regular_hits_fail():
    search = GithubFocusedFallbackSearchClient()
    tools = ResearchTools(
        search_client=search,
        page_extractor=MultiUrlFailingPageExtractor({"https://openai.com/index/codex/"}),
        github_signals=FakeGitHubSignalsClient(),
    )

    bundle = tools.build_evidence_bundle(subject="OpenAI Codex", url="https://openai.com/index/codex/")

    assert bundle["positioning"]["source_url"] == "https://github.com/openai/codex/landing"
    assert bundle["diagnostics"]["resolved_via"] == "github_search_hit"
    assert search.queries == ["OpenAI Codex", "OpenAI Codex github"]


class FirecrawlSubdomainSearchClient:
    def search(self, query: str, max_results: int = 5) -> list[SearchHit]:
        return [
            SearchHit(
                title="Firecrawl Docs",
                url="https://docs.firecrawl.dev",
                snippet="Official docs for Firecrawl.",
            )
        ]


class FirecrawlGithubSignalsClient:
    def lookup(self, query: str) -> list[dict[str, str | int]]:
        return [
            {"repo": "acme/docs-agent", "stars": 10, "updated_at": "2026-03-31T00:00:00Z"},
            {"repo": "firecrawl/firecrawl", "stars": 9000, "updated_at": "2026-03-31T00:00:00Z"},
        ]


def test_search_competitor_candidates_uses_registered_domain_identity_not_subdomain_label():
    tools = ResearchTools(
        search_client=FirecrawlSubdomainSearchClient(),
        page_extractor=FakePageExtractor(),
        github_signals=FirecrawlGithubSignalsClient(),
    )

    candidates = tools.search_competitor_candidates(
        target="Claude Code",
        hypothesis="crawler",
        source_mix=["web", "github"],
        max_results=5,
    )
    urls = {item["canonical_url"] for item in candidates}

    assert "https://github.com/acme/docs-agent" in urls
    assert "https://github.com/firecrawl/firecrawl" not in urls


class AgentAiSearchClient:
    def search(self, query: str, max_results: int = 5) -> list[SearchHit]:
        return [
            SearchHit(
                title="Agent AI",
                url="https://agent.ai",
                snippet="Agent AI platform.",
            )
        ]


class AgentAiGithubSignalsClient:
    def lookup(self, query: str) -> list[dict[str, str | int]]:
        return [
            {"repo": "acme/agent-kit", "stars": 700, "updated_at": "2026-03-31T00:00:00Z"},
            {"repo": "agent/agent", "stars": 5000, "updated_at": "2026-03-31T00:00:00Z"},
        ]


def test_search_competitor_candidates_does_not_drop_github_repo_on_generic_token_overlap():
    tools = ResearchTools(
        search_client=AgentAiSearchClient(),
        page_extractor=FakePageExtractor(),
        github_signals=AgentAiGithubSignalsClient(),
    )

    candidates = tools.search_competitor_candidates(
        target="Claude Code",
        hypothesis="agent tooling",
        source_mix=["web", "github"],
        max_results=5,
    )
    urls = {item["canonical_url"] for item in candidates}

    assert "https://agent.ai" in urls
    assert "https://github.com/acme/agent-kit" in urls
    assert "https://github.com/agent/agent" not in urls


class RankedFirecrawlSearchClient:
    def search(self, query: str, max_results: int = 5) -> list[SearchHit]:
        return [
            SearchHit(
                title="Firecrawl Docs",
                url="https://docs.firecrawl.dev/",
                snippet="Documentation site.",
            ),
            SearchHit(
                title="Firecrawl",
                url="https://www.firecrawl.dev/?utm_source=test",
                snippet="Official site.",
            ),
        ]


def test_search_competitor_candidates_prefers_root_site_and_normalizes_urls():
    tools = ResearchTools(
        search_client=RankedFirecrawlSearchClient(),
        page_extractor=FakePageExtractor(),
        github_signals=FirecrawlGithubSignalsClient(),
    )

    candidates = tools.search_competitor_candidates(
        target="Claude Code",
        hypothesis="crawler",
        source_mix=["web", "github"],
        max_results=5,
    )
    urls = [item["canonical_url"] for item in candidates]

    assert urls[0] == "https://firecrawl.dev"
    assert "https://docs.firecrawl.dev" not in urls
    assert "https://github.com/firecrawl/firecrawl" not in urls


def test_search_competitor_candidates_prefers_reachable_root_site_over_unreachable_docs_hit():
    class SearchClient:
        def search(self, query: str, max_results: int = 5) -> list[SearchHit]:
            return [
                SearchHit(title="Foo Docs", url="https://docs.foo.dev", snippet="Docs."),
                SearchHit(title="Foo", url="https://foo.dev", snippet="Official site."),
            ]

    class PageExtractor:
        def extract(self, url: str) -> PageData:
            if url == "https://docs.foo.dev":
                raise RuntimeError("docs blocked")
            return PageData(url=url, title="Foo", text="Official site", excerpt="Official site")

    tools = ResearchTools(
        search_client=SearchClient(),
        page_extractor=PageExtractor(),
        github_signals=FakeGitHubSignalsClient(),
    )

    candidates = tools.search_competitor_candidates(
        target="Claude Code",
        hypothesis="agent",
        source_mix=["web"],
        max_results=5,
    )

    assert candidates[0]["canonical_url"] == "https://foo.dev"
    assert candidates[0]["candidate_quality"]["url_precheck"] == "ok"
    assert all(item["canonical_url"] != "https://docs.foo.dev" for item in candidates)


def test_search_competitor_candidates_skips_article_like_review_pages_before_precheck():
    class SearchClient:
        def search(self, query: str, max_results: int = 5) -> list[SearchHit]:
            return [
                SearchHit(
                    title="Windsurf review",
                    url="https://awesomeagents.ai/reviews/review-windsurf",
                    snippet="Independent review page.",
                ),
                SearchHit(
                    title="Windsurf",
                    url="https://windsurf.com",
                    snippet="Official site.",
                ),
            ]

    class RecordingPageExtractor:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def extract(self, url: str) -> PageData:
            self.calls.append(url)
            return PageData(url=url, title="title", text="text", excerpt="excerpt")

    extractor = RecordingPageExtractor()
    tools = ResearchTools(
        search_client=SearchClient(),
        page_extractor=extractor,
        github_signals=FakeGitHubSignalsClient(),
    )

    candidates = tools.search_competitor_candidates(
        target="Claude Code",
        hypothesis="coding agent",
        source_mix=["web"],
        max_results=5,
    )

    assert [item["canonical_url"] for item in candidates] == ["https://windsurf.com"]
    assert extractor.calls == ["https://windsurf.com"]


def test_search_competitor_candidates_falls_back_to_hypothesis_query_when_target_query_is_article_only():
    class SearchClient:
        def __init__(self) -> None:
            self.queries: list[str] = []

        def search(self, query: str, max_results: int = 5) -> list[SearchHit]:
            self.queries.append(query)
            if query == "Claude Code competitor coding agent":
                return [
                    SearchHit(
                        title="Claude Code alternatives",
                        url="https://awesomeagents.ai/reviews/review-windsurf",
                        snippet="Independent review page.",
                    )
                ]
            return [
                SearchHit(
                    title="Windsurf",
                    url="https://windsurf.com",
                    snippet="Official site.",
                )
            ]

    search = SearchClient()
    tools = ResearchTools(
        search_client=search,
        page_extractor=FakePageExtractor(),
        github_signals=FakeGitHubSignalsClient(),
    )

    candidates = tools.search_competitor_candidates(
        target="Claude Code",
        hypothesis="coding agent",
        source_mix=["web"],
        max_results=5,
    )

    assert search.queries == ["Claude Code competitor coding agent", "coding agent"]
    assert [item["canonical_url"] for item in candidates] == ["https://windsurf.com"]


def test_search_competitor_candidates_uses_richer_github_activity_signals_in_rank():
    class GithubSignalsClient:
        def lookup(self, query: str) -> list[dict[str, str | int]]:
            return [
                {
                    "repo": "acme/legacy-agent",
                    "stars": 5000,
                    "updated_at": "2025-01-01T00:00:00Z",
                    "latest_commit_at": "2025-01-01T00:00:00Z",
                    "latest_release_tag": "",
                },
                {
                    "repo": "acme/active-agent",
                    "stars": 3200,
                    "updated_at": "2026-04-01T00:00:00Z",
                    "latest_commit_at": "2026-04-01T00:00:00Z",
                    "latest_release_tag": "v1.4.0",
                },
            ]

    tools = ResearchTools(
        search_client=EmptySearchClient(),
        page_extractor=FakePageExtractor(),
        github_signals=GithubSignalsClient(),
    )

    candidates = tools.search_competitor_candidates(
        target="Claude Code",
        hypothesis="coding agent",
        source_mix=["github"],
        max_results=5,
    )

    assert candidates[0]["canonical_url"] == "https://github.com/acme/active-agent"


def test_research_tools_matches_agent_facing_protocol_and_signature():
    tools = ResearchTools(
        search_client=FakeSearchClient(),
        page_extractor=FakePageExtractor(),
        github_signals=FakeGitHubSignalsClient(),
    )

    assert isinstance(tools, ResearchToolset)
    assert "github_signals" in inspect.signature(ResearchTools.__init__).parameters


def test_http_page_extractor_uses_final_response_url():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/start":
            return httpx.Response(status_code=302, headers={"location": "https://example.com/final"}, request=request)
        return httpx.Response(
            status_code=200,
            text="<html><head><title>Final</title></head><body>Hello Final</body></html>",
            request=request,
        )

    extractor = HttpPageExtractor(http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    page = extractor.extract("https://example.com/start")

    assert page.url == "https://example.com/final"


def test_exa_search_client_maps_payload_to_search_hits():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL("https://api.exa.ai/search")
        assert request.headers["x-api-key"] == "test-key"
        payload = request.read().decode("utf-8")
        assert '"query":"claude code competitors"' in payload
        assert '"numResults":3' in payload
        assert '"type":"auto"' in payload
        assert '"contents":{"highlights":{"numSentences":2}}' in payload
        return httpx.Response(
            status_code=200,
            json={
                "results": [
                    {
                        "title": "Aider",
                        "url": "https://aider.chat",
                        "highlights": ["Terminal AI pair programmer"],
                    },
                    {"title": "Missing Url", "highlights": ["ignored"]},
                ]
            },
            request=request,
        )

    client = ExaSearchClient(api_key="test-key", http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    hits = client.search("claude code competitors", max_results=3)

    assert len(hits) == 1
    assert hits[0].title == "Aider"
    assert hits[0].url == "https://aider.chat"
    assert hits[0].snippet == "Terminal AI pair programmer"


def test_github_signals_maps_payload_to_lookup_results():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/search/repositories"
        return httpx.Response(
            status_code=200,
            json={
                "items": [
                    {
                        "full_name": "Aider-AI/aider",
                        "stargazers_count": 24000,
                        "updated_at": "2026-03-29T10:00:00Z",
                    }
                ]
            },
            request=request,
        )

    signals = GitHubSignals(http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    result = signals.lookup("aider")

    assert result == [
        {
            "repo": "Aider-AI/aider",
            "stars": 24000,
            "updated_at": "2026-03-29T10:00:00Z",
            "forks": 0,
            "open_issues": 0,
            "default_branch": "",
            "description": "",
            "latest_release_tag": "",
            "latest_release_published_at": "",
            "latest_commit_at": "",
        }
    ]


def test_github_signals_enriches_repo_results_with_release_and_commit_metadata():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/search/repositories":
            return httpx.Response(
                status_code=200,
                json={
                    "items": [
                        {
                            "full_name": "Aider-AI/aider",
                            "stargazers_count": 24000,
                            "updated_at": "2026-03-29T10:00:00Z",
                            "forks_count": 2100,
                            "open_issues_count": 320,
                            "default_branch": "main",
                            "description": "AI pair programmer in your terminal.",
                        }
                    ]
                },
                request=request,
            )
        if request.url.path == "/repos/Aider-AI/aider/releases/latest":
            return httpx.Response(
                status_code=200,
                json={"tag_name": "v0.81.0", "published_at": "2026-03-28T00:00:00Z"},
                request=request,
            )
        if request.url.path == "/repos/Aider-AI/aider/commits":
            return httpx.Response(
                status_code=200,
                json=[{"commit": {"committer": {"date": "2026-03-29T09:00:00Z"}}}],
                request=request,
            )
        raise AssertionError(request.url.path)

    signals = GitHubSignals(http_client=httpx.Client(transport=httpx.MockTransport(handler)))

    result = signals.lookup("aider")

    assert result == [
        {
            "repo": "Aider-AI/aider",
            "stars": 24000,
            "updated_at": "2026-03-29T10:00:00Z",
            "forks": 2100,
            "open_issues": 320,
            "default_branch": "main",
            "description": "AI pair programmer in your terminal.",
            "latest_release_tag": "v0.81.0",
            "latest_release_published_at": "2026-03-28T00:00:00Z",
            "latest_commit_at": "2026-03-29T09:00:00Z",
        }
    ]


def test_github_signals_keeps_base_repo_result_when_release_lookup_fails():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/search/repositories":
            return httpx.Response(
                status_code=200,
                json={
                    "items": [
                        {
                            "full_name": "acme/agent-kit",
                            "stargazers_count": 900,
                            "updated_at": "2026-03-30T00:00:00Z",
                        }
                    ]
                },
                request=request,
            )
        if request.url.path == "/repos/acme/agent-kit/releases/latest":
            return httpx.Response(status_code=404, json={"message": "Not Found"}, request=request)
        if request.url.path == "/repos/acme/agent-kit/commits":
            return httpx.Response(status_code=200, json=[], request=request)
        raise AssertionError(request.url.path)

    signals = GitHubSignals(http_client=httpx.Client(transport=httpx.MockTransport(handler)))

    result = signals.lookup("agent-kit")

    assert result[0]["repo"] == "acme/agent-kit"
    assert result[0]["stars"] == 900
    assert result[0]["latest_release_tag"] == ""
    assert result[0]["latest_commit_at"] == ""


def test_exa_search_client_disables_env_proxy_for_default_httpx_requests(monkeypatch):
    captured = {}

    def fake_post(url: str, *, json: dict[str, object], headers: dict[str, str], timeout: float, trust_env: bool):
        captured["url"] = url
        captured["trust_env"] = trust_env
        return httpx.Response(
            status_code=200,
            json={"results": [{"title": "Aider", "url": "https://aider.chat", "highlights": ["snippet"]}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr("jingyantai.tools.web_search.httpx.post", fake_post)
    client = ExaSearchClient(api_key="test-key")

    hits = client.search("claude code competitors", max_results=3)

    assert len(hits) == 1
    assert captured["url"] == "https://api.exa.ai/search"
    assert captured["trust_env"] is False


def test_exa_search_client_retries_after_connect_error_and_then_succeeds():
    class FlakyClient:
        def __init__(self) -> None:
            self.calls = 0

        def post(self, url: str, *, json: dict[str, object], headers: dict[str, str], timeout: float):
            self.calls += 1
            if self.calls == 1:
                raise httpx.ConnectError("temporary failure", request=httpx.Request("POST", url))
            return httpx.Response(
                status_code=200,
                json={"results": [{"title": "Aider", "url": "https://aider.chat", "highlights": ["snippet"]}]},
                request=httpx.Request("POST", url),
            )

    client = ExaSearchClient(api_key="test-key", http_client=FlakyClient(), max_retries=1)

    hits = client.search("claude code competitors", max_results=3)

    assert len(hits) == 1


def test_http_page_extractor_disables_env_proxy_for_default_httpx_requests(monkeypatch):
    captured = {}

    def fake_get(url: str, *, timeout: float, headers: dict[str, str], follow_redirects: bool, trust_env: bool):
        captured["url"] = url
        captured["trust_env"] = trust_env
        captured["headers"] = headers
        return httpx.Response(
            status_code=200,
            text="<html><head><title>Example</title></head><body>Hello</body></html>",
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr("jingyantai.tools.page_extract.httpx.get", fake_get)
    extractor = HttpPageExtractor()

    page = extractor.extract("https://example.com")

    assert page.title == "Example"
    assert captured["url"] == "https://example.com"
    assert captured["trust_env"] is False
    assert "Mozilla/5.0" in captured["headers"]["User-Agent"]
    assert "text/html" in captured["headers"]["Accept"]
    assert captured["headers"]["Accept-Language"].startswith("en")


def test_github_signals_disables_env_proxy_for_default_httpx_requests(monkeypatch):
    captured = {}

    def fake_get(url: str, *, params: dict[str, object], headers: dict[str, str], timeout: float, trust_env: bool):
        captured["url"] = url
        captured["trust_env"] = trust_env
        return httpx.Response(
            status_code=200,
            json={"items": []},
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr("jingyantai.tools.github_signals.httpx.get", fake_get)
    signals = GitHubSignals()

    result = signals.lookup("aider")

    assert result == []
    assert captured["url"] == "https://api.github.com/search/repositories"
    assert captured["trust_env"] is False
