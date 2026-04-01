import inspect

import httpx

from jingyantai.tools.contracts import PageData, ResearchToolset, SearchHit
from jingyantai.tools.page_extract import HttpPageExtractor
from jingyantai.tools.research_tools import ResearchTools


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
    def lookup(self, query: str) -> list[dict[str, str | int]]:
        return [
            {"repo": "acme/agent-kit", "stars": 900, "releases": 11},
            {"repo": "acme/workflow-kit", "stars": 500, "releases": 6},
        ]


def test_search_competitor_candidates_returns_structured_candidates():
    search = FakeSearchClient()
    tools = ResearchTools(
        search_client=search,
        page_extractor=FakePageExtractor(),
        github_signals=FakeGitHubSignalsClient(),
    )

    candidates = tools.search_competitor_candidates(
        target="Claude Code",
        hypothesis="coding agent",
        source_mix=["web", "github"],
        max_results=2,
    )

    assert len(candidates) == 2
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
    assert "Claude Code competitor coding agent" in search.queries[0]


def test_collect_market_heat_signals_merges_search_page_and_github_signals():
    page = FakePageExtractor()
    tools = ResearchTools(
        search_client=FakeSearchClient(),
        page_extractor=page,
        github_signals=FakeGitHubSignalsClient(),
    )

    signals = tools.collect_market_heat_signals(subject="coding agent", max_results=1)

    assert signals["summary"].startswith("coding agent")
    assert len(signals["web_signals"]) == 1
    assert signals["web_signals"][0]["source_url"] == "https://codeium.com/landing"
    assert signals["web_signals"][0]["page_excerpt"] == "Weekly active developers grew quickly in Q1."
    assert signals["github"][0]["repo"] == "acme/agent-kit"
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


def test_build_evidence_bundle_uses_pricing_or_access_key_and_single_fetch():
    page = FakePageExtractor()
    tools = ResearchTools(
        search_client=EmptySearchClient(),
        page_extractor=page,
        github_signals=FakeGitHubSignalsClient(),
    )

    bundle = tools.build_evidence_bundle(subject="Aider", url="https://aider.chat")

    assert set(bundle.keys()) == {"positioning", "workflow", "pricing_or_access", "github", "heat"}
    assert bundle["pricing_or_access"]["dimension"] == "pricing or access"
    assert bundle["positioning"]["source_url"] == "https://aider.chat/landing"
    assert bundle["workflow"]["source_url"] == "https://aider.chat/landing"
    assert bundle["pricing_or_access"]["source_url"] == "https://aider.chat/landing"
    assert page.calls == 1


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
