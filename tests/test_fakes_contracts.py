from __future__ import annotations

from jingyantai.domain.models import BudgetPolicy, ResearchBrief, RunCharter, StopDecision
from jingyantai.domain.phases import StopVerdict

from jingyantai.agents.prompts import ROLE_PROMPTS

from tests.fakes import FakeInitializer, FakeStopJudge


def test_fake_initializer_run_returns_brief_and_charter():
    brief, charter = FakeInitializer().run("Claude Code")

    assert isinstance(brief, ResearchBrief)
    assert isinstance(brief.budget, BudgetPolicy)
    assert brief.target == "Claude Code"
    assert brief.product_type == "coding-agent"
    assert (
        brief.competitor_definition
        == "Direct competitors are terminal-native coding agents for software engineers."
    )
    assert brief.required_dimensions == [
        "positioning",
        "workflow",
        "core capabilities",
        "pricing or access",
        "community / ecosystem signal",
    ]
    assert brief.stop_policy == "Stop after enough confirmed competitors with coverage."

    assert isinstance(charter, RunCharter)
    assert charter.mission == "Research competitors for Claude Code"
    assert charter.scope == ["direct competitors", "terminal coding agents"]
    assert charter.non_goals == ["broad LLM platform analysis"]
    assert charter.success_criteria == ["3 confirmed competitors", "all required dimensions covered"]
    assert charter.research_agenda == ["expand", "deepen", "challenge"]


def test_fake_stop_judge_run_returns_stop_decision():
    decision = FakeStopJudge(StopVerdict.CONTINUE).run(None)

    assert isinstance(decision, StopDecision)
    assert decision.verdict == StopVerdict.CONTINUE
    assert decision.reasons == ["test verdict"]


def test_role_prompts_registry_contains_all_plan_keys():
    expected_keys = {
        "initializer",
        "lead_researcher",
        "scout_positioning",
        "scout_github",
        "scout_heat",
        "analyst_workflow",
        "analyst_pricing",
        "analyst_positioning",
        "evidence_judge",
        "coverage_judge",
        "challenger",
        "stop_judge",
        "synthesizer",
        "citation_agent",
    }
    assert expected_keys.issubset(ROLE_PROMPTS.keys())
