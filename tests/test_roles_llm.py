from __future__ import annotations

from jingyantai.agents.roles import AnalystRole, InitializerRole, LeadResearcherRole, ScoutRole
from jingyantai.agents.schemas import AnalystOutput, InitializerOutput, ScoutOutput
from jingyantai.domain.models import BudgetPolicy, Candidate, RunState
from jingyantai.domain.phases import CandidateStatus, Phase


class FakeToolset:
    def __init__(self) -> None:
        self.search_calls: list[tuple[str, str, list[str], int]] = []
        self.bundle_calls: list[tuple[str, str]] = []

    def search_competitor_candidates(self, target, hypothesis, source_mix, max_results=5):
        self.search_calls.append((target, hypothesis, source_mix, max_results))
        return [
            {
                "candidate_id": "cand-aider",
                "name": "Aider",
                "canonical_url": "https://aider.chat",
                "why_candidate": "terminal coding agent",
            }
        ]

    def build_evidence_bundle(self, subject, url):
        self.bundle_calls.append((subject, url))
        return {
            "positioning": {"summary": "Terminal coding agent", "source_url": "https://aider.chat"},
            "workflow": {"summary": "Terminal workflow", "source_url": "https://aider.chat/docs"},
            "pricing_or_access": {
                "summary": "Open source",
                "source_url": "https://github.com/Aider-AI/aider",
            },
            "github": [],
            "heat": {},
        }


class StaticAdapter:
    def __init__(self, output, *, provider="deepseek", model="deepseek-chat"):
        self.output = output
        self.provider = provider
        self.model = model
        self.calls: list[tuple[dict[str, object], object]] = []

    def run(self, payload, model_type):
        self.calls.append((payload, model_type))
        return model_type.model_validate(self.output)


class FailingAdapter:
    provider = "deepseek"
    model = "deepseek-chat"

    def run(self, payload, model_type):
        raise RuntimeError("adapter failed")


def _budget() -> BudgetPolicy:
    return BudgetPolicy(
        max_rounds=4,
        max_active_candidates=8,
        max_deepen_targets=3,
        max_external_fetches=30,
        max_run_duration_minutes=20,
    )


def test_initializer_role_maps_output_to_brief_and_charter():
    adapter = StaticAdapter(
        InitializerOutput(
            brief_target="Claude Code",
            product_type="coding-agent",
            competitor_definition="Direct competitors are terminal-native coding agents.",
            required_dimensions=["positioning", "workflow"],
            stop_policy="Stop after enough covered competitors.",
            charter_mission="Research direct competitors for Claude Code",
            charter_scope=["terminal-native coding agents"],
            charter_non_goals=["broad platform comparison"],
            charter_success_criteria=["3 confirmed competitors"],
            charter_research_agenda=["expand", "deepen"],
        )
    )
    role = InitializerRole(adapter=adapter, budget=_budget())

    brief, charter = role.run("Claude Code")

    assert brief.target == "Claude Code"
    assert charter.mission == "Research direct competitors for Claude Code"
    assert role.provider == "deepseek"
    assert role.model == "deepseek-chat"


def test_lead_researcher_role_falls_back_when_adapter_fails():
    state = RunState(run_id="run-1", target="Claude Code", current_phase=Phase.EXPAND, budget=_budget())
    role = LeadResearcherRole(adapter=FailingAdapter())

    plan = role.run(state)

    assert "Expand and deepen direct competitors for Claude Code" == plan
    assert role.provider == "deepseek"
    assert role.model == "deepseek-chat"


def test_scout_role_calls_tools_and_maps_model_output():
    tools = FakeToolset()
    adapter = StaticAdapter(
        ScoutOutput.model_validate(
            {
                "candidates": [
                    {
                        "name": "Aider",
                        "canonical_url": "https://aider.chat",
                        "why_candidate": "terminal coding agent",
                    }
                ]
            }
        )
    )
    role = ScoutRole(
        tools=tools,
        adapter=adapter,
        hypothesis="terminal coding agent",
        role_name="scout_positioning",
    )
    state = RunState(
        run_id="run-1",
        target="Claude Code",
        current_phase=Phase.EXPAND,
        budget=_budget(),
        carry_forward_context="carry context",
    )

    candidates = role.run(state)

    assert tools.search_calls == [("Claude Code", "terminal coding agent", ["web", "github"], 5)]
    assert adapter.calls[0][0]["target"] == "Claude Code"
    assert adapter.calls[0][0]["raw_candidates"][0]["name"] == "Aider"
    assert candidates[0].name == "Aider"
    assert role.role_name == "scout_positioning"
    assert role.provider == "deepseek"
    assert role.model == "deepseek-chat"


def test_analyst_role_calls_tools_and_maps_model_output():
    tools = FakeToolset()
    adapter = StaticAdapter(
        AnalystOutput.model_validate(
            {
                "evidence": [
                    {
                        "claim": "Runs in terminal",
                        "source_url": "https://aider.chat",
                        "source_type": "official",
                        "snippet": "terminal",
                        "supports_or_conflicts": "supports",
                        "confidence": 0.8,
                        "freshness_score": 0.9,
                    }
                ],
                "findings": [
                    {
                        "dimension": "workflow",
                        "summary": "Terminal workflow overlap",
                        "evidence_refs": [0],
                        "confidence": 0.8,
                    }
                ],
                "uncertainties": [
                    {
                        "statement": "Pricing unclear",
                        "impact": "medium",
                        "resolvability": "search-more",
                        "required_evidence": "pricing page",
                    }
                ],
            }
        )
    )
    role = AnalystRole(
        tools=tools,
        adapter=adapter,
        dimension="workflow",
        role_name="analyst_workflow",
    )
    state = RunState(
        run_id="run-1",
        target="Claude Code",
        current_phase=Phase.DEEPEN,
        budget=_budget(),
        carry_forward_context="carry context",
    )
    candidate = Candidate(
        candidate_id="cand-aider",
        name="Aider",
        canonical_url="https://aider.chat",
        status=CandidateStatus.CONFIRMED,
        relevance_score=0.9,
        why_candidate="direct",
    )

    evidence, findings, uncertainties = role.run(state, candidate)

    assert tools.bundle_calls == [("Aider", "https://aider.chat")]
    assert adapter.calls[0][0]["candidate"]["candidate_id"] == "cand-aider"
    assert adapter.calls[0][0]["bundle"]["workflow"]["summary"] == "Terminal workflow"
    assert findings[0].dimension == "workflow"
    assert uncertainties[0].statement == "Pricing unclear"
    assert role.role_name == "analyst_workflow"
    assert role.provider == "deepseek"
    assert role.model == "deepseek-chat"
