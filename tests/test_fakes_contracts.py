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
    assert brief.competitor_definition == "Terminal-based coding agents"
    assert brief.required_dimensions == ["positioning", "workflow", "pricing"]
    assert brief.stop_policy == "stop when confidence is high"

    assert isinstance(charter, RunCharter)
    assert charter.mission == "Competitive research charter for Claude Code."
    assert charter.scope == ["positioning", "github", "heat", "workflow", "pricing"]


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
