from __future__ import annotations

from jingyantai.agents.roles import AnalystRole, InitializerRole, LeadResearcherRole, ScoutRole
from jingyantai.agents.schemas import AnalystOutput, InitializerOutput, LeadResearcherOutput, ScoutOutput
from jingyantai.domain.models import BudgetPolicy, Candidate, GapTicket, RunState
from jingyantai.domain.phases import CandidateStatus, GapPriority, Phase
from jingyantai.runtime.policies import QualityRubric
from jingyantai.tools.contracts import ToolExecutionMetrics


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


def test_initializer_role_falls_back_when_adapter_fails():
    role = InitializerRole(adapter=FailingAdapter(), budget=_budget())

    brief, charter = role.run("Claude Code")

    assert brief.target == "Claude Code"
    assert brief.product_type == "coding-agent"
    assert "terminal-native coding agents" in brief.competitor_definition
    assert charter.mission == "Research competitors for Claude Code"
    assert role.provider == "deepseek"
    assert role.model == "deepseek-chat"


def test_lead_researcher_role_falls_back_when_adapter_fails():
    state = RunState(run_id="run-1", target="Claude Code", current_phase=Phase.EXPAND, budget=_budget())
    role = LeadResearcherRole(adapter=FailingAdapter())

    plan = role.run(state)

    assert "Expand and deepen direct competitors for Claude Code" == plan
    assert role.provider == "deepseek"
    assert role.model == "deepseek-chat"


def test_lead_researcher_role_passes_structured_memory_and_watchlist_to_adapter():
    from jingyantai.agents.schemas import LeadResearcherOutput

    adapter = StaticAdapter(LeadResearcherOutput(round_plan="Use prior research memory."))
    role = LeadResearcherRole(adapter=adapter)
    state = RunState(
        run_id="run-1",
        target="Claude Code",
        current_phase=Phase.EXPAND,
        budget=_budget(),
        carry_forward_context="carry context",
        memory_snapshot={
            "top_competitors": ["Legacy One"],
            "unresolved_uncertainties": ["Legacy pricing uncertainty"],
        },
        watchlist=[
            {
                "entity_name": "Legacy One",
                "canonical_url": "https://legacy.example",
                "watch_reason": "pricing uncertainty",
                "revisit_trigger": "pricing page changes",
                "priority": "high",
                "last_seen_run_id": "run-prev",
            }
        ],
    )

    plan = role.run(state)

    assert plan == "Use prior research memory."
    assert adapter.calls[0][0]["memory_snapshot"]["top_competitors"] == ["Legacy One"]
    assert adapter.calls[0][0]["watchlist"][0]["entity_name"] == "Legacy One"
    assert adapter.calls[0][0]["quality_rubric"]["required_dimensions"] == [
        "positioning",
        "workflow",
        "pricing or access",
    ]


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
        memory_snapshot={"top_competitors": ["Legacy One"]},
        watchlist=[{"entity_name": "Legacy One", "priority": "high"}],
    )

    candidates = role.run(state)

    assert tools.search_calls == [("Claude Code", "terminal coding agent", ["web", "github"], 5)]
    assert adapter.calls[0][0]["target"] == "Claude Code"
    assert adapter.calls[0][0]["memory_snapshot"]["top_competitors"] == ["Legacy One"]
    assert adapter.calls[0][0]["watchlist"][0]["entity_name"] == "Legacy One"
    assert adapter.calls[0][0]["quality_rubric"]["evidence_confidence_threshold"] == 0.6
    assert adapter.calls[0][0]["raw_candidates"][0]["name"] == "Aider"
    assert candidates[0].name == "Aider"
    assert role.role_name == "scout_positioning"
    assert role.provider == "deepseek"
    assert role.model == "deepseek-chat"


def test_scout_role_preserves_tool_metrics_when_adapter_fails():
    class MetricsToolset(FakeToolset):
        def consume_last_metrics(self):
            return ToolExecutionMetrics(
                external_fetches=2,
                fetch_breakdown={"search": 1, "github_lookup": 1},
                notes=["phase runtime deadline exceeded before external fetch"],
            )

    tools = MetricsToolset()
    role = ScoutRole(
        tools=tools,
        adapter=FailingAdapter(),
        hypothesis="terminal coding agent",
        role_name="scout_positioning",
    )
    state = RunState(
        run_id="run-1",
        target="Claude Code",
        current_phase=Phase.EXPAND,
        budget=_budget(),
    )

    try:
        role.run(state)
    except RuntimeError as exc:
        assert str(exc) == "adapter failed"
    else:
        raise AssertionError("expected adapter failure")

    assert role.last_tool_metrics == ToolExecutionMetrics(
        external_fetches=2,
        fetch_breakdown={"search": 1, "github_lookup": 1},
        notes=["phase runtime deadline exceeded before external fetch"],
    )


def test_scout_role_preserves_tool_metrics_when_tools_raise():
    class FailingMetricsToolset(FakeToolset):
        def search_competitor_candidates(self, target, hypothesis, source_mix, max_results=5):
            raise TimeoutError("page extract timed out")

        def consume_last_metrics(self):
            return ToolExecutionMetrics(
                external_fetches=2,
                fetch_breakdown={"search": 1, "page_extract": 1},
                notes=["page extract timed out after 0.005s"],
            )

    role = ScoutRole(
        tools=FailingMetricsToolset(),
        adapter=StaticAdapter(ScoutOutput.model_validate({"candidates": []})),
        hypothesis="terminal coding agent",
        role_name="scout_positioning",
    )
    state = RunState(
        run_id="run-1",
        target="Claude Code",
        current_phase=Phase.EXPAND,
        budget=_budget(),
    )

    try:
        role.run(state)
    except TimeoutError as exc:
        assert str(exc) == "page extract timed out"
    else:
        raise AssertionError("expected tool timeout")

    assert role.last_tool_metrics == ToolExecutionMetrics(
        external_fetches=2,
        fetch_breakdown={"search": 1, "page_extract": 1},
        notes=["page extract timed out after 0.005s"],
    )


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
        memory_snapshot={"top_competitors": ["Legacy One"]},
        watchlist=[{"entity_name": "Legacy One", "priority": "high"}],
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
    assert adapter.calls[0][0]["memory_snapshot"]["top_competitors"] == ["Legacy One"]
    assert adapter.calls[0][0]["watchlist"][0]["entity_name"] == "Legacy One"
    assert adapter.calls[0][0]["quality_rubric"]["required_dimensions"] == [
        "positioning",
        "workflow",
        "pricing or access",
    ]
    assert adapter.calls[0][0]["bundle"]["workflow"]["summary"] == "Terminal workflow"


def test_analyst_role_passes_dimension_specific_bundle_through_to_adapter():
    tools = FakeToolset()
    tools.build_evidence_bundle = lambda subject, url: {
        "positioning": {"summary": "Official site", "source_url": "https://aider.chat"},
        "workflow": {"summary": "Docs", "source_url": "https://aider.chat/docs"},
        "pricing_or_access": {"summary": "Pricing", "source_url": "https://aider.chat/pricing"},
        "github": [{"repo": "Aider-AI/aider", "latest_release_tag": "v0.81.0"}],
        "heat": {},
        "diagnostics": {"dimension_sources": {"workflow": "workflow_search_hit"}},
    }
    adapter = StaticAdapter(AnalystOutput.model_validate({"evidence": [], "findings": [], "uncertainties": []}))
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
    )
    candidate = Candidate(
        candidate_id="cand-aider",
        name="Aider",
        canonical_url="https://aider.chat",
        status=CandidateStatus.CONFIRMED,
        relevance_score=0.9,
        why_candidate="direct",
    )

    role.run(state, candidate)

    assert adapter.calls[0][0]["bundle"]["workflow"]["source_url"] == "https://aider.chat/docs"
    assert adapter.calls[0][0]["bundle"]["pricing_or_access"]["source_url"] == "https://aider.chat/pricing"
    assert adapter.calls[0][0]["bundle"]["diagnostics"]["dimension_sources"]["workflow"] == "workflow_search_hit"
    assert role.role_name == "analyst_workflow"
    assert role.provider == "deepseek"
    assert role.model == "deepseek-chat"


def test_analyst_role_preserves_tool_metrics_when_adapter_fails():
    class MetricsToolset(FakeToolset):
        def consume_last_metrics(self):
            return ToolExecutionMetrics(
                external_fetches=1,
                fetch_breakdown={"page_extract": 1},
                notes=["primary extract failed"],
            )

    role = AnalystRole(
        tools=MetricsToolset(),
        adapter=FailingAdapter(),
        dimension="workflow",
        role_name="analyst_workflow",
    )
    state = RunState(
        run_id="run-1",
        target="Claude Code",
        current_phase=Phase.DEEPEN,
        budget=_budget(),
    )
    candidate = Candidate(
        candidate_id="cand-aider",
        name="Aider",
        canonical_url="https://aider.chat",
        status=CandidateStatus.CONFIRMED,
        relevance_score=0.9,
        why_candidate="direct",
    )

    try:
        role.run(state, candidate)
    except RuntimeError as exc:
        assert str(exc) == "adapter failed"
    else:
        raise AssertionError("expected adapter failure")

    assert role.last_tool_metrics == ToolExecutionMetrics(
        external_fetches=1,
        fetch_breakdown={"page_extract": 1},
        notes=["primary extract failed"],
    )


def test_analyst_role_preserves_tool_metrics_when_tools_raise():
    class FailingMetricsToolset(FakeToolset):
        def build_evidence_bundle(self, subject, url):
            raise TimeoutError("primary extract timed out")

        def consume_last_metrics(self):
            return ToolExecutionMetrics(
                external_fetches=1,
                fetch_breakdown={"page_extract": 1},
                notes=["primary extract timed out after 0.050s"],
            )

    role = AnalystRole(
        tools=FailingMetricsToolset(),
        adapter=StaticAdapter(AnalystOutput.model_validate({"evidence": [], "findings": [], "uncertainties": []})),
        dimension="workflow",
        role_name="analyst_workflow",
    )
    state = RunState(
        run_id="run-1",
        target="Claude Code",
        current_phase=Phase.DEEPEN,
        budget=_budget(),
    )
    candidate = Candidate(
        candidate_id="cand-aider",
        name="Aider",
        canonical_url="https://aider.chat",
        status=CandidateStatus.CONFIRMED,
        relevance_score=0.9,
        why_candidate="direct",
    )

    try:
        role.run(state, candidate)
    except TimeoutError as exc:
        assert str(exc) == "primary extract timed out"
    else:
        raise AssertionError("expected tool timeout")

    assert role.last_tool_metrics == ToolExecutionMetrics(
        external_fetches=1,
        fetch_breakdown={"page_extract": 1},
        notes=["primary extract timed out after 0.050s"],
    )


def test_roles_accept_custom_quality_rubric():
    from jingyantai.agents.schemas import LeadResearcherOutput

    rubric = QualityRubric(
        required_dimensions=["workflow", "pricing"],
        evidence_confidence_threshold=0.75,
        evidence_freshness_threshold=0.4,
    )
    adapter = StaticAdapter(LeadResearcherOutput(round_plan="Follow custom rubric."))
    role = LeadResearcherRole(adapter=adapter, quality_rubric=rubric)
    state = RunState(
        run_id="run-1",
        target="Claude Code",
        current_phase=Phase.EXPAND,
        budget=_budget(),
    )

    role.run(state)

    assert adapter.calls[0][0]["quality_rubric"] == rubric.model_dump(mode="json")


def test_roles_forward_quality_rubric_calibration_examples_to_adapter():
    rubric = QualityRubric(
        calibration_examples=[
            {
                "role_scope": "analyst",
                "verdict": "edge_case",
                "example": "Keep one fallback GitHub source when the official page is blocked.",
                "lesson": "Fallback evidence is acceptable only when it reduces a named uncertainty.",
            }
        ]
    )
    tools = FakeToolset()
    adapter = StaticAdapter(
        AnalystOutput.model_validate({"evidence": [], "findings": [], "uncertainties": []})
    )
    role = AnalystRole(
        tools=tools,
        adapter=adapter,
        dimension="workflow",
        role_name="analyst_workflow",
        quality_rubric=rubric,
    )
    state = RunState(
        run_id="run-1",
        target="Claude Code",
        current_phase=Phase.DEEPEN,
        budget=_budget(),
    )
    candidate = Candidate(
        candidate_id="cand-aider",
        name="Aider",
        canonical_url="https://aider.chat",
        status=CandidateStatus.CONFIRMED,
        relevance_score=0.9,
        why_candidate="direct",
    )

    role.run(state, candidate)

    assert adapter.calls[0][0]["quality_rubric"]["calibration_examples"] == [
        {
            "role_scope": "analyst",
            "verdict": "edge_case",
            "example": "Keep one fallback GitHub source when the official page is blocked.",
            "lesson": "Fallback evidence is acceptable only when it reduces a named uncertainty.",
        }
    ]


def test_roles_pass_execution_focus_payload_to_adapter():
    adapter = StaticAdapter(LeadResearcherOutput(round_plan="Focus on pricing gap."))
    role = LeadResearcherRole(adapter=adapter)
    state = RunState(
        run_id="run-1",
        target="Claude Code",
        current_phase=Phase.EXPAND,
        budget=_budget(),
        memory_snapshot={
            "top_competitors": ["Legacy One"],
            "repeated_failure_patterns": ["pricing loop"],
        },
        watchlist=[
            {
                "entity_name": "Legacy One",
                "canonical_url": "https://legacy.example",
                "watch_reason": "pricing gap",
                "revisit_trigger": "pricing page changes",
                "priority": "high",
                "last_seen_run_id": "run-prev",
            }
        ],
        gap_tickets=[
            GapTicket(
                gap_type="coverage",
                target_scope="Legacy One",
                blocking_reason="Missing dimensions: pricing or access",
                owner_role="analyst",
                acceptance_rule="Cover pricing with direct evidence.",
                deadline_round=1,
                priority=GapPriority.HIGH,
            )
        ],
    )

    role.run(state)

    assert adapter.calls[0][0]["execution_focus"]["priority_gaps"] == [
        "Legacy One: Missing dimensions: pricing or access"
    ]
    assert adapter.calls[0][0]["execution_focus"]["watchlist_entities"] == ["Legacy One"]
    assert adapter.calls[0][0]["execution_focus"]["repeated_failures"] == ["pricing loop"]


def test_roles_forward_historical_memory_payload_to_adapter():
    from jingyantai.agents.schemas import LeadResearcherOutput

    adapter = StaticAdapter(LeadResearcherOutput(round_plan="Use cross-run memory."))
    role = LeadResearcherRole(adapter=adapter)
    state = RunState(
        run_id="run-1",
        target="Claude Code",
        current_phase=Phase.EXPAND,
        budget=_budget(),
        historical_memory={
            "recent_runs": [
                {
                    "run_id": "run-prev",
                    "target": "Claude Code",
                    "confirmed_entities": ["Aider"],
                    "unresolved_uncertainties": ["Pricing unclear"],
                    "trusted_sources": ["https://aider.chat"],
                    "repeated_failure_patterns": ["timeout on pricing page"],
                }
            ],
            "recurring_competitors": ["Aider"],
            "recurring_uncertainties": ["Pricing unclear"],
            "recurring_trusted_sources": ["https://aider.chat"],
            "recurring_failure_patterns": ["timeout on pricing page"],
        },
    )

    role.run(state)

    assert adapter.calls[0][0]["historical_memory"]["recent_runs"][0]["run_id"] == "run-prev"
    assert adapter.calls[0][0]["historical_memory"]["recurring_competitors"] == ["Aider"]
    assert adapter.calls[0][0]["historical_memory"]["recurring_trusted_sources"] == ["https://aider.chat"]
