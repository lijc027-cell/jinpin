from __future__ import annotations

from jingyantai.domain.models import (
    BudgetPolicy,
    Candidate,
    Evidence,
    Finding,
    ResearchBrief,
    RunCharter,
    UncertaintyItem,
)
from jingyantai.domain.phases import CandidateStatus
from jingyantai.tools.contracts import ResearchToolset


def _default_budget() -> BudgetPolicy:
    return BudgetPolicy(
        max_rounds=4,
        max_active_candidates=8,
        max_deepen_targets=3,
        max_external_fetches=30,
        max_run_duration_minutes=20,
    )


class InitializerRole:
    def run(self, target: str) -> tuple[ResearchBrief, RunCharter]:
        return (
            ResearchBrief(
                target=target,
                product_type="coding-agent",
                competitor_definition="Direct competitors are terminal-native coding agents for software engineers.",
                required_dimensions=[
                    "positioning",
                    "workflow",
                    "core capabilities",
                    "pricing or access",
                    "community / ecosystem signal",
                ],
                stop_policy="Stop after at least 3 confirmed competitors meet evidence and coverage gates.",
                budget=_default_budget(),
            ),
            RunCharter(
                mission=f"Research direct competitors for {target}",
                scope=["terminal-native coding agents", "developer workflows", "pricing and ecosystem signals"],
                non_goals=["broad foundation-model vendor comparison"],
                success_criteria=[
                    "3 confirmed competitors",
                    "minimum evidence gate met",
                    "challenger has no blocking objection",
                ],
                research_agenda=["expand candidates", "deepen evidence", "challenge fit", "stop when covered"],
            ),
        )


class LeadResearcherRole:
    def run(self, state) -> str:
        if state.gap_tickets:
            return f"Address gap tickets for: {', '.join(ticket.target_scope for ticket in state.gap_tickets)}"
        return f"Expand and deepen direct competitors for {state.target}"


class ScoutRole:
    def __init__(self, tools: ResearchToolset, hypothesis: str) -> None:
        self.tools = tools
        self.hypothesis = hypothesis

    def run(self, state) -> list[Candidate]:
        raw_candidates = self.tools.search_competitor_candidates(state.target, self.hypothesis, ["web", "github"])
        return [
            Candidate(
                candidate_id=item["candidate_id"],
                name=item["name"],
                canonical_url=item["canonical_url"],
                status=CandidateStatus.DISCOVERED,
                relevance_score=0.75,
                why_candidate=item["why_candidate"],
            )
            for item in raw_candidates
        ]


class AnalystRole:
    def __init__(self, tools: ResearchToolset, dimension: str) -> None:
        self.tools = tools
        self.dimension = dimension

    def run(self, state, candidate: Candidate) -> tuple[list[Evidence], list[Finding], list[UncertaintyItem]]:
        bundle = self.tools.build_evidence_bundle(candidate.name, candidate.canonical_url)
        bundle_key = {
            "positioning": "positioning",
            "workflow": "workflow",
            "pricing or access": "pricing_or_access",
        }.get(self.dimension, "pricing_or_access")
        selected = bundle[bundle_key]

        evidence = Evidence(
            evidence_id=f"e-{candidate.candidate_id}-{self.dimension}",
            subject_id=candidate.candidate_id,
            claim=selected["summary"][:160],
            source_url=selected["source_url"],
            source_type="official",
            snippet=selected["summary"][:280],
            captured_at="2026-04-01",
            freshness_score=0.9,
            confidence=0.85,
        )
        finding = Finding(
            finding_id=f"f-{candidate.candidate_id}-{self.dimension}",
            subject_id=candidate.candidate_id,
            dimension=self.dimension,
            summary=selected["summary"][:200],
            evidence_ids=[evidence.evidence_id],
            confidence=0.85,
        )
        uncertainty = UncertaintyItem(
            statement=f"Need more detail for {candidate.name} on {self.dimension}",
            impact="medium",
            resolvability="search-more",
            required_evidence=f"Additional {self.dimension} sources",
            owner_role="analyst",
        )
        return [evidence], [finding], [uncertainty]
