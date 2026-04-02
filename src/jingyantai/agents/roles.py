from __future__ import annotations

from jingyantai.agents.deepagents_adapter import DeepagentsRoleAdapter
from jingyantai.agents.mappers import AnalystMapper, InitializerMapper, ScoutMapper
from jingyantai.agents.schemas import AnalystOutput, InitializerOutput, LeadResearcherOutput, ScoutOutput
from jingyantai.domain.models import (
    BudgetPolicy,
    Candidate,
    Evidence,
    Finding,
    ResearchBrief,
    RunCharter,
    UncertaintyItem,
)
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
    def __init__(self, adapter: DeepagentsRoleAdapter, budget: BudgetPolicy | None = None) -> None:
        self.adapter = adapter
        self.budget = budget or _default_budget()
        self.provider = adapter.provider
        self.model = adapter.model

    def run(self, target: str) -> tuple[ResearchBrief, RunCharter]:
        output = self.adapter.run({"target": target}, InitializerOutput)
        return InitializerMapper().map(output, self.budget)


class LeadResearcherRole:
    def __init__(self, adapter: DeepagentsRoleAdapter) -> None:
        self.adapter = adapter
        self.provider = adapter.provider
        self.model = adapter.model

    def run(self, state) -> str:
        try:
            output = self.adapter.run(
                {
                    "target": state.target,
                    "round_index": state.round_index,
                    "current_phase": getattr(state.current_phase, "value", state.current_phase),
                    "gap_tickets": [
                        ticket.model_dump() if hasattr(ticket, "model_dump") else dict(ticket)
                        for ticket in state.gap_tickets
                    ],
                    "carry_forward_context": state.carry_forward_context,
                },
                LeadResearcherOutput,
            )
            return output.round_plan
        except Exception:
            if state.gap_tickets:
                scopes = ", ".join(ticket.target_scope for ticket in state.gap_tickets)
                return f"Address gap tickets for: {scopes}"
            return f"Expand and deepen direct competitors for {state.target}"


class ScoutRole:
    def __init__(self, tools: ResearchToolset, adapter: DeepagentsRoleAdapter, hypothesis: str, role_name: str) -> None:
        self.tools = tools
        self.adapter = adapter
        self.hypothesis = hypothesis
        self.role_name = role_name
        self.provider = adapter.provider
        self.model = adapter.model

    def run(self, state) -> list[Candidate]:
        raw_candidates = self.tools.search_competitor_candidates(state.target, self.hypothesis, ["web", "github"])
        output = self.adapter.run(
            {
                "target": state.target,
                "hypothesis": self.hypothesis,
                "carry_forward_context": state.carry_forward_context,
                "raw_candidates": raw_candidates,
            },
            ScoutOutput,
        )
        return ScoutMapper().map(output)


class AnalystRole:
    def __init__(self, tools: ResearchToolset, adapter: DeepagentsRoleAdapter, dimension: str, role_name: str) -> None:
        self.tools = tools
        self.adapter = adapter
        self.dimension = dimension
        self.role_name = role_name
        self.provider = adapter.provider
        self.model = adapter.model

    def run(self, state, candidate: Candidate) -> tuple[list[Evidence], list[Finding], list[UncertaintyItem]]:
        bundle = self.tools.build_evidence_bundle(candidate.name, candidate.canonical_url)
        output = self.adapter.run(
            {
                "candidate": candidate.model_dump(),
                "dimension": self.dimension,
                "carry_forward_context": state.carry_forward_context,
                "bundle": bundle,
            },
            AnalystOutput,
        )
        return AnalystMapper().map(candidate, self.dimension, output)
