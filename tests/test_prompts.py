from __future__ import annotations

from jingyantai.agents.prompts import get_role_prompt
from jingyantai.runtime.policies import QualityRubric


def test_lead_researcher_prompt_explicitly_uses_memory_watchlist_and_rubric():
    prompt = get_role_prompt(
        "lead_researcher",
        rubric=QualityRubric(
            required_dimensions=["workflow", "pricing or access"],
            evidence_confidence_threshold=0.75,
            evidence_freshness_threshold=0.35,
        ),
    )

    assert "memory_snapshot" in prompt
    assert "watchlist" in prompt
    assert "quality_rubric" in prompt
    assert "workflow" in prompt
    assert "pricing or access" in prompt
    assert "one goal cluster" in prompt


def test_analyst_prompt_contains_calibration_style_rules_for_evidence_and_uncertainty():
    prompt = get_role_prompt(
        "analyst_pricing",
        rubric=QualityRubric(
            required_dimensions=["pricing or access"],
            evidence_confidence_threshold=0.8,
            evidence_freshness_threshold=0.5,
        ),
    )

    assert "Only extract evidence that is supported by the bundle" in prompt
    assert "If the bundle cannot support a claim" in prompt
    assert "0.8" in prompt
    assert "0.5" in prompt
    assert "uncertainty" in prompt.lower()


def test_lead_researcher_prompt_requires_gap_ticket_driven_next_round_plan():
    prompt = get_role_prompt("lead_researcher", rubric=QualityRubric.default())

    assert "gap_tickets" in prompt
    assert "execution_focus" in prompt
    assert "Do not restate the entire mission" in prompt
    assert "Choose the smallest next step that can close a named gap" in prompt


def test_scout_and_analyst_prompts_include_positive_and_negative_calibration_examples():
    scout = get_role_prompt("scout_github", rubric=QualityRubric.default())
    analyst = get_role_prompt("analyst_workflow", rubric=QualityRubric.default())

    assert "Good pattern" in scout
    assert "Bad pattern" in scout
    assert "Prefer candidates that close a current gap ticket" in scout

    assert "Good pattern" in analyst
    assert "Bad pattern" in analyst
    assert "If execution_focus says this dimension is not the bottleneck" in analyst


def test_prompt_renders_structured_calibration_examples_from_quality_rubric():
    prompt = get_role_prompt(
        "scout_github",
        rubric=QualityRubric(
            calibration_examples=[
                {
                    "role_scope": "scout",
                    "verdict": "pass",
                    "example": "Keep the official repo and canonical product URL only.",
                    "lesson": "Prefer the candidate that can close a named gap with direct product evidence.",
                },
                {
                    "role_scope": "scout",
                    "verdict": "fail",
                    "example": "Promote a blog post because it mentions many tools.",
                    "lesson": "Content pages are not competitor entities.",
                },
                {
                    "role_scope": "scout",
                    "verdict": "edge_case",
                    "example": "Keep one GitHub repo when the official site blocks extraction but repo signals are fresh.",
                    "lesson": "Allow repo fallback only when it materially improves evidence quality.",
                },
            ]
        ),
    )

    assert "Calibration examples from quality_rubric" in prompt
    assert "pass: Keep the official repo and canonical product URL only." in prompt
    assert "fail: Promote a blog post because it mentions many tools." in prompt
    assert "edge_case: Keep one GitHub repo when the official site blocks extraction but repo signals are fresh." in prompt


def test_prompts_explicitly_reference_historical_memory_for_cross_run_context():
    lead = get_role_prompt("lead_researcher", rubric=QualityRubric.default())
    scout = get_role_prompt("scout_github", rubric=QualityRubric.default())
    analyst = get_role_prompt("analyst_workflow", rubric=QualityRubric.default())

    assert "historical_memory" in lead
    assert "historical_memory" in scout
    assert "historical_memory" in analyst
