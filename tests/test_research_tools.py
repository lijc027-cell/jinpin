import inspect

import httpx

from jingyantai.tools.contracts import PageData, ResearchToolset, SearchHit
from jingyantai.tools.github_signals import GitHubSignals
from jingyantai.tools.page_extract import HttpPageExtractor
from jingyantai.tools.research_tools import ResearchTools
from jingyantai.tools.web_search import TavilySearchClient


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


def test_build_evidence_bundle_fetches_main_url_once_but_allows_heat_pages():
    page = TrackingPageExtractor()
    tools = ResearchTools(
        search_client=FakeSearchClient(),
        page_extractor=page,
        github_signals=FakeGitHubSignalsClient(),
    )

    bundle = tools.build_evidence_bundle(subject="Aider", url="https://aider.chat")

    assert set(bundle.keys()) == {"positioning", "workflow", "pricing_or_access", "github", "heat"}
    assert bundle["pricing_or_access"]["dimension"] == "pricing or access"
    assert bundle["positioning"]["source_url"] == "https://aider.chat/landing"
    assert bundle["workflow"]["source_url"] == "https://aider.chat/landing"
    assert bundle["pricing_or_access"]["source_url"] == "https://aider.chat/landing"
    assert page.urls.count("https://aider.chat") == 1
    assert "https://codeium.com" in page.urls


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

    assert set(bundle.keys()) == {"positioning", "workflow", "pricing_or_access", "github", "heat"}
    assert "summary" in bundle["heat"]
    assert len(bundle["heat"]["search"]) == 2


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


def test_tavily_search_client_maps_payload_to_search_hits():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL("https://api.tavily.com/search")
        payload = request.read().decode("utf-8")
        assert '"query":"claude code competitors"' in payload
        return httpx.Response(
            status_code=200,
            json={
                "results": [
                    {"title": "Aider", "url": "https://aider.chat", "content": "Terminal AI pair programmer"},
                    {"title": "Missing Url", "content": "ignored"},
                ]
            },
            request=request,
        )

    client = TavilySearchClient(api_key="test-key", http_client=httpx.Client(transport=httpx.MockTransport(handler)))
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
        }
    ]
