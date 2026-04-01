from jingyantai.tools.contracts import PageData, SearchHit
from jingyantai.tools.research_tools import ResearchTools


class FakeSearchClient:
    def search(self, query: str, max_results: int = 5) -> list[SearchHit]:
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


class FakePageExtractor:
    def extract(self, url: str) -> PageData:
        return PageData(
            url=url,
            title="Market Traction Update",
            text="Weekly active developers grew quickly in Q1.",
            excerpt="Weekly active developers grew quickly in Q1.",
        )


class FakeGitHubSignalsClient:
    def collect(self, query: str, limit: int = 5) -> dict[str, object]:
        return {
            "query": query,
            "repo_count": 2,
            "total_stars": 1400,
            "repositories": [
                {"full_name": "acme/agent-kit", "stars": 900},
                {"full_name": "acme/workflow-kit", "stars": 500},
            ],
        }


def test_search_competitor_candidates_returns_structured_candidates():
    tools = ResearchTools(
        search_client=FakeSearchClient(),
        page_extractor=FakePageExtractor(),
        github_signals_client=FakeGitHubSignalsClient(),
    )

    candidates = tools.search_competitor_candidates(
        target="Claude Code",
        product_type="coding agent",
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


def test_collect_market_heat_signals_merges_search_page_and_github_signals():
    tools = ResearchTools(
        search_client=FakeSearchClient(),
        page_extractor=FakePageExtractor(),
        github_signals_client=FakeGitHubSignalsClient(),
    )

    signals = tools.collect_market_heat_signals(topic="coding agent", max_results=1)

    assert signals["topic"] == "coding agent"
    assert len(signals["web_signals"]) == 1
    assert signals["web_signals"][0]["source_url"] == "https://codeium.com"
    assert signals["web_signals"][0]["page_excerpt"] == "Weekly active developers grew quickly in Q1."
    assert signals["github_signals"]["repo_count"] == 2
    assert signals["signal_count"] == 3
