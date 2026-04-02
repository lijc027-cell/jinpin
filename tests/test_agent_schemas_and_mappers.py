from __future__ import annotations

import pytest

from jingyantai.agents.mappers import AnalystMapper, InitializerMapper, ScoutMapper
from jingyantai.agents.schemas import AnalystOutput, InitializerOutput, ScoutCandidateDraft, ScoutOutput
from jingyantai.domain.models import BudgetPolicy, Candidate
from jingyantai.domain.phases import CandidateStatus


def test_initializer_mapper_builds_brief_and_charter_with_local_budget():
    output = InitializerOutput(
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
    budget = BudgetPolicy(
        max_rounds=4,
        max_active_candidates=8,
        max_deepen_targets=3,
        max_external_fetches=30,
        max_run_duration_minutes=20,
    )

    brief, charter = InitializerMapper().map(output, budget)

    assert brief.budget == budget
    assert charter.mission == "Research direct competitors for Claude Code"


def test_scout_mapper_generates_discovered_candidate_with_clamped_score():
    output = ScoutOutput(
        candidates=[
            ScoutCandidateDraft(
                name="Aider",
                canonical_url="https://aider.chat",
                why_candidate="terminal coding agent",
                company="Aider",
                aliases=["aider"],
                suggested_relevance=1.2,
            )
        ]
    )

    candidates = ScoutMapper().map(output)

    assert candidates[0].candidate_id.startswith("cand-aider")
    assert candidates[0].status == CandidateStatus.DISCOVERED
    assert candidates[0].relevance_score == 1.0


def test_analyst_mapper_builds_linked_evidence_and_findings():
    candidate = Candidate(
        candidate_id="cand-aider",
        name="Aider",
        canonical_url="https://aider.chat",
        status=CandidateStatus.CONFIRMED,
        relevance_score=0.9,
        why_candidate="direct",
    )
    output = AnalystOutput.model_validate(
        {
            "evidence": [
                {
                    "claim": "Aider runs in the terminal",
                    "source_url": "https://aider.chat",
                    "source_type": "official",
                    "snippet": "AI pair programmer in your terminal",
                    "supports_or_conflicts": "supports",
                    "confidence": 0.8,
                    "freshness_score": 0.9,
                }
            ],
            "findings": [
                {
                    "dimension": "workflow",
                    "summary": "Aider overlaps on terminal workflow",
                    "evidence_refs": [0],
                    "confidence": 0.8,
                }
            ],
            "uncertainties": [
                {
                    "statement": "Pricing still unclear",
                    "impact": "medium",
                    "resolvability": "search-more",
                    "required_evidence": "pricing page",
                }
            ],
        }
    )

    evidence, findings, uncertainties = AnalystMapper().map(candidate, "workflow", output)

    assert evidence[0].subject_id == "cand-aider"
    assert findings[0].evidence_ids == [evidence[0].evidence_id]
    assert uncertainties[0].owner_role == "analyst"


def test_analyst_mapper_rejects_out_of_range_evidence_reference():
    candidate = Candidate(
        candidate_id="cand-aider",
        name="Aider",
        canonical_url="https://aider.chat",
        status=CandidateStatus.CONFIRMED,
        relevance_score=0.9,
        why_candidate="direct",
    )
    output = AnalystOutput.model_validate(
        {
            "evidence": [
                {
                    "claim": "Aider runs in the terminal",
                    "source_url": "https://aider.chat",
                    "source_type": "official",
                    "snippet": "AI pair programmer in your terminal",
                    "supports_or_conflicts": "supports",
                    "confidence": 0.8,
                    "freshness_score": 0.9,
                }
            ],
            "findings": [
                {
                    "dimension": "workflow",
                    "summary": "Aider overlaps on terminal workflow",
                    "evidence_refs": [2],
                    "confidence": 0.8,
                }
            ],
            "uncertainties": [],
        }
    )

    with pytest.raises(ValueError, match="Invalid evidence reference"):
        AnalystMapper().map(candidate, "workflow", output)
