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
from jingyantai.runtime.policies import QualityRubric
from jingyantai.tools.contracts import ResearchToolset


def _default_budget() -> BudgetPolicy:
    return BudgetPolicy(
        max_rounds=4,
        max_active_candidates=8,
        max_deepen_targets=3,
        max_external_fetches=30,
        max_run_duration_minutes=20,
    )


def _fallback_brief_and_charter(target: str, budget: BudgetPolicy) -> tuple[ResearchBrief, RunCharter]:
    brief = ResearchBrief(
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
        stop_policy="Stop after enough confirmed competitors with coverage.",
        budget=budget,
    )
    charter = RunCharter(
        mission=f"Research competitors for {target}",
        scope=["direct competitors", "terminal coding agents"],
        non_goals=["broad LLM platform analysis"],
        success_criteria=["3 confirmed competitors", "all required dimensions covered"],
        research_agenda=["expand", "deepen", "challenge"],
    )
    return brief, charter


def _memory_payload(state: object) -> dict[str, object]:
    payload = getattr(state, "memory_snapshot", {}) or {}
    return payload if isinstance(payload, dict) else {}


def _watchlist_payload(state: object) -> list[dict[str, object]]:
    payload = getattr(state, "watchlist", []) or []
    return [item for item in payload if isinstance(item, dict)]


def _historical_memory_payload(state: object) -> dict[str, object]:
    payload = getattr(state, "historical_memory", {}) or {}
    return payload if isinstance(payload, dict) else {}


def _execution_focus_payload(
    state: object,
    *,
    owner_role: str | None = None,
    dimension: str | None = None,
) -> dict[str, object]:
    gap_tickets = getattr(state, "gap_tickets", []) or []
    snapshot = _memory_payload(state)
    watchlist = _watchlist_payload(state)

    priority_gaps: list[str] = []
    for ticket in gap_tickets:
        ticket_owner = str(getattr(ticket, "owner_role", ""))
        if owner_role not in {None, "lead_researcher"} and ticket_owner not in {owner_role, "lead_researcher"}:
            continue
        summary = f"{getattr(ticket, 'target_scope', 'run')}: {getattr(ticket, 'blocking_reason', '')}".strip()
        if not summary or summary == ":":
            continue
        if dimension is not None:
            lowered_summary = summary.lower()
            if dimension.lower() not in lowered_summary and "missing dimensions" not in lowered_summary:
                continue
        priority_gaps.append(summary)

    return {
        "priority_gaps": priority_gaps[:3],
        "watchlist_entities": [str(item.get("entity_name", "")) for item in watchlist[:3] if item.get("entity_name")],
        "repeated_failures": [str(item) for item in snapshot.get("repeated_failure_patterns", [])[:3]],
        "top_competitors": [str(item) for item in snapshot.get("top_competitors", [])[:3]],
    }


def _rubric_payload(rubric: QualityRubric) -> dict[str, object]:
    return rubric.model_dump(mode="json")


class InitializerRole:
    def __init__(self, adapter: DeepagentsRoleAdapter, budget: BudgetPolicy | None = None) -> None:
        self.adapter = adapter
        self.budget = budget or _default_budget()
        self.provider = adapter.provider
        self.model = adapter.model

    def run(self, target: str) -> tuple[ResearchBrief, RunCharter]:
        try:
            output = self.adapter.run({"target": target}, InitializerOutput)
            return InitializerMapper().map(output, self.budget)
        except Exception:
            return _fallback_brief_and_charter(target, self.budget)


class LeadResearcherRole:
    def __init__(self, adapter: DeepagentsRoleAdapter, quality_rubric: QualityRubric | None = None) -> None:
        self.adapter = adapter
        self.quality_rubric = quality_rubric or QualityRubric.default()
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
                    "memory_snapshot": _memory_payload(state),
                    "historical_memory": _historical_memory_payload(state),
                    "watchlist": _watchlist_payload(state),
                    "execution_focus": _execution_focus_payload(state, owner_role="lead_researcher"),
                    "quality_rubric": _rubric_payload(self.quality_rubric),
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
    def __init__(
        self,
        tools: ResearchToolset,
        adapter: DeepagentsRoleAdapter,
        hypothesis: str,
        role_name: str,
        quality_rubric: QualityRubric | None = None,
    ) -> None:
        self.tools = tools
        self.adapter = adapter
        self.hypothesis = hypothesis
        self.role_name = role_name
        self.quality_rubric = quality_rubric or QualityRubric.default()
        self.provider = adapter.provider
        self.model = adapter.model
        self.last_tool_metrics = None
        self.source_mix = ["web", "github"]
        self.search_max_results = 5
        self.cache_only = False

    def run(self, state) -> list[Candidate]:
        consume = getattr(self.tools, "consume_last_metrics", None)
        try:
            raw_candidates = self.tools.search_competitor_candidates(
                state.target,
                self.hypothesis,
                list(self.source_mix),
                max_results=self.search_max_results,
            )
            output = self.adapter.run(
                {
                    "target": state.target,
                    "hypothesis": self.hypothesis,
                    "memory_snapshot": _memory_payload(state),
                    "historical_memory": _historical_memory_payload(state),
                    "watchlist": _watchlist_payload(state),
                    "execution_focus": _execution_focus_payload(state, owner_role="scout"),
                    "quality_rubric": _rubric_payload(self.quality_rubric),
                    "carry_forward_context": state.carry_forward_context,
                    "raw_candidates": raw_candidates,
                },
                ScoutOutput,
            )
            return ScoutMapper().map(output)
        finally:
            if callable(consume):
                self.last_tool_metrics = consume()


class AnalystRole:
    def __init__(
        self,
        tools: ResearchToolset,
        adapter: DeepagentsRoleAdapter,
        dimension: str,
        role_name: str,
        quality_rubric: QualityRubric | None = None,
    ) -> None:
        self.tools = tools
        self.adapter = adapter
        self.dimension = dimension
        self.role_name = role_name
        self.quality_rubric = quality_rubric or QualityRubric.default()
        self.provider = adapter.provider
        self.model = adapter.model
        self.last_tool_metrics = None

    def run(self, state, candidate: Candidate) -> tuple[list[Evidence], list[Finding], list[UncertaintyItem]]:
        consume = getattr(self.tools, "consume_last_metrics", None)
        try:
            bundle = self.tools.build_evidence_bundle(candidate.name, candidate.canonical_url)
            output = self.adapter.run(
                {
                    "candidate": candidate.model_dump(),
                    "dimension": self.dimension,
                    "memory_snapshot": _memory_payload(state),
                    "historical_memory": _historical_memory_payload(state),
                    "watchlist": _watchlist_payload(state),
                    "execution_focus": _execution_focus_payload(
                        state,
                        owner_role="analyst",
                        dimension=self.dimension,
                    ),
                    "quality_rubric": _rubric_payload(self.quality_rubric),
                    "carry_forward_context": state.carry_forward_context,
                    "bundle": bundle,
                },
                AnalystOutput,
            )
            return AnalystMapper().map(candidate, self.dimension, output)
        finally:
            if callable(consume):
                self.last_tool_metrics = consume()
