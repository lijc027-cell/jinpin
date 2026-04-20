from __future__ import annotations

import json
from pathlib import Path

import pytest

from jingyantai.agents.deepagents_adapter import DeepagentsRoleAdapter
from jingyantai.agents.roles import LeadResearcherRole
from jingyantai.agents.schemas import LeadResearcherOutput
from jingyantai.domain.models import BudgetPolicy, RunState
from jingyantai.domain.phases import Phase, StopVerdict
from jingyantai.llm.contracts import ModelInvocation, ProviderConfig
from jingyantai.runtime.compactor import ContextCompactor
from jingyantai.runtime.contracts import RoundContract
from jingyantai.runtime.controller import HarnessController
from jingyantai.runtime.memory import FileMemoryStore, MemorySnapshot, RunMemoryEntry
from jingyantai.runtime.policies import DegradeAction, PhasePolicy, RuntimePolicy
from jingyantai.storage.run_store import FileRunStore
from jingyantai.tools.contracts import ToolExecutionMetrics
from fakes import FakeInitializer


class FakeLeadResearcher:
    def run(self, state):
        return "Investigate terminal-native coding agents and deepen top candidates."


class FakeScout:
    def __init__(self, suffix: str):
        self.suffix = suffix

    def run(self, state):
        from jingyantai.domain.models import Candidate
        from jingyantai.domain.phases import CandidateStatus

        return [
            Candidate(
                candidate_id=f"{self.suffix}-1",
                name=f"{self.suffix} Candidate",
                canonical_url=f"https://{self.suffix}.dev",
                status=CandidateStatus.DISCOVERED,
                relevance_score=0.8,
                why_candidate="terminal coding agent",
            )
        ]


class FakeAnalyst:
    def run(self, state, candidate):
        from jingyantai.domain.models import Evidence, Finding

        evidence = Evidence(
            evidence_id=f"e-{candidate.candidate_id}",
            subject_id=candidate.candidate_id,
            claim=f"{candidate.name} is a direct competitor",
            source_url=candidate.canonical_url,
            source_type="official",
            snippet="Direct evidence",
            captured_at="2026-04-01",
            freshness_score=0.95,
            confidence=0.95,
        )
        finding = Finding(
            finding_id=f"f-{candidate.candidate_id}",
            subject_id=candidate.candidate_id,
            dimension="positioning",
            summary=f"{candidate.name} overlaps with Claude Code",
            evidence_ids=[evidence.evidence_id],
            confidence=0.95,
        )
        return [evidence], [finding], []


class SequentialStopJudge:
    def __init__(self, verdicts):
        self.verdicts = verdicts
        self.index = 0

    def run(self, state):
        from jingyantai.domain.models import GapTicket, StopDecision
        from jingyantai.domain.phases import GapPriority

        verdict = self.verdicts[min(self.index, len(self.verdicts) - 1)]
        self.index += 1
        if verdict == StopVerdict.CONTINUE:
            return StopDecision(
                verdict=verdict,
                reasons=["Need one more deepen pass"],
                gap_tickets=[
                    GapTicket(
                        gap_type="coverage",
                        target_scope="confirmed_candidates",
                        blocking_reason="Need another workflow pass",
                        owner_role="analyst",
                        acceptance_rule="Add one more workflow finding",
                        deadline_round=state.round_index + 1,
                        priority=GapPriority.HIGH,
                    )
                ],
            )
        return StopDecision(verdict=verdict, reasons=["Enough coverage"])


def test_controller_loops_until_stop_and_persists_state(tmp_path: Path):
    store = FileRunStore(tmp_path / "runs")
    controller = HarnessController(
        store=store,
        initializer=FakeInitializer(),
        lead_researcher=FakeLeadResearcher(),
        scouts=[FakeScout("aider"), FakeScout("codex"), FakeScout("opencode")],
        analysts=[FakeAnalyst()],
        compactor=ContextCompactor(),
        evidence_judge=lambda state: None,
        coverage_judge=lambda state: None,
        challenger=lambda state: None,
        stop_judge=SequentialStopJudge([StopVerdict.CONTINUE, StopVerdict.STOP]),
    )

    final_state = controller.run(
        target="Claude Code",
        budget=BudgetPolicy(
            max_rounds=4,
            max_active_candidates=8,
            max_deepen_targets=3,
            max_external_fetches=30,
            max_run_duration_minutes=20,
        ),
    )

    assert final_state.current_phase.value == "stop"
    assert store.load_state(final_state.run_id).target == "Claude Code"
    assert final_state.round_index == 1
    assert "Claude Code" in final_state.carry_forward_context
    assert len(final_state.traces) >= 2


def test_controller_generates_unique_run_ids():
    controller = HarnessController(
        store=object(),
        initializer=FakeInitializer(),
        lead_researcher=FakeLeadResearcher(),
        scouts=[],
        analysts=[],
        compactor=ContextCompactor(),
        evidence_judge=lambda state: None,
        coverage_judge=lambda state: None,
        challenger=lambda state: None,
        stop_judge=SequentialStopJudge([StopVerdict.STOP]),
    )

    first = controller._new_run_id()
    second = controller._new_run_id()

    assert first.startswith("run-")
    assert second.startswith("run-")
    assert first != second


def test_controller_emits_stop_reason_when_round_budget_is_exhausted(tmp_path: Path):
    from jingyantai.domain.models import StopDecision

    class AlwaysContinueStopJudge:
        def run(self, state):
            return StopDecision(verdict=StopVerdict.CONTINUE, reasons=["not enough coverage"], gap_tickets=[])

    controller = HarnessController(
        store=FileRunStore(tmp_path / "runs"),
        initializer=FakeInitializer(),
        lead_researcher=FakeLeadResearcher(),
        scouts=[],
        analysts=[],
        compactor=ContextCompactor(),
        evidence_judge=lambda state: None,
        coverage_judge=lambda state: None,
        challenger=lambda state: None,
        stop_judge=AlwaysContinueStopJudge(),
    )

    final_state = controller.run(
        target="Claude Code",
        budget=BudgetPolicy(
            max_rounds=0,
            max_active_candidates=8,
            max_deepen_targets=3,
            max_external_fetches=30,
            max_run_duration_minutes=20,
        ),
    )

    assert final_state.current_phase == Phase.STOP
    assert final_state.stop_reason is not None
    assert "round budget exhausted" in final_state.stop_reason
    assert final_state.round_index == 1

    log_path = tmp_path / "runs" / final_state.run_id / "artifacts" / "evaluator-log.jsonl"
    records = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert any(
        record.get("event_type") == "forced_stop"
        and isinstance(record.get("stop_reason"), str)
        and "round budget exhausted" in record["stop_reason"]
        for record in records
    )

    progress_path = tmp_path / "runs" / final_state.run_id / "artifacts" / "progress-log.jsonl"
    progress_records = [json.loads(line) for line in progress_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert any(
        isinstance(record.get("stop_reason"), str) and "round budget exhausted" in record["stop_reason"]
        for record in progress_records
    )


def test_controller_records_role_errors_and_continues_for_scout_and_analyst_failures(tmp_path: Path):
    from jingyantai.domain.models import Candidate, StopDecision
    from jingyantai.domain.phases import CandidateStatus

    class PassingLeadResearcher:
        def run(self, state):
            return "Plan next pass"

    class FailingScout:
        provider = "deepseek"
        model = "deepseek-chat"
        role_name = "scout_positioning"

        def run(self, state):
            raise RuntimeError("scout failed")

    class HealthyScout:
        provider = "deepseek"
        model = "deepseek-chat"
        role_name = "scout_github"

        def run(self, state):
            return [
                Candidate(
                    candidate_id="cand-aider-1",
                    name="Aider",
                    canonical_url="https://aider.chat",
                    status=CandidateStatus.DISCOVERED,
                    relevance_score=0.8,
                    why_candidate="terminal coding agent",
                )
            ]

    class FailingAnalyst:
        provider = "deepseek"
        model = "deepseek-chat"
        role_name = "analyst_workflow"

        def run(self, state, candidate):
            raise RuntimeError("analyst failed")

    class StopNow:
        def run(self, state):
            return StopDecision(verdict=StopVerdict.STOP, reasons=["done"], gap_tickets=[])

    store = FileRunStore(tmp_path / "runs")
    controller = HarnessController(
        store=store,
        initializer=FakeInitializer(),
        lead_researcher=PassingLeadResearcher(),
        scouts=[FailingScout(), HealthyScout()],
        analysts=[FailingAnalyst()],
        compactor=ContextCompactor(),
        evidence_judge=lambda state: None,
        coverage_judge=lambda state: None,
        challenger=lambda state: None,
        stop_judge=StopNow(),
    )

    final_state = controller.run(target="Claude Code", budget=BudgetPolicy(
        max_rounds=4,
        max_active_candidates=8,
        max_deepen_targets=3,
        max_external_fetches=30,
        max_run_duration_minutes=20,
    ))

    all_errors = [error for trace in final_state.traces for error in trace.role_errors]
    assert any("scout_positioning|deepseek|deepseek-chat|runtime_error|RuntimeError|scout failed" in item for item in all_errors)
    assert any("analyst_workflow|deepseek|deepseek-chat|runtime_error|RuntimeError|analyst failed" in item for item in all_errors)
    assert any(candidate.name == "Aider" for candidate in final_state.candidates)


def test_controller_records_phase_metrics_tool_metrics_and_diagnostics(tmp_path: Path):
    from jingyantai.domain.models import Candidate, Evidence, Finding, StopDecision
    from jingyantai.domain.phases import CandidateStatus

    class IncrementingClock:
        def __init__(self) -> None:
            self.current = 0.0

        def __call__(self) -> float:
            self.current += 0.01
            return self.current

    class PassingLeadResearcher:
        role_name = "lead_researcher"

        def run(self, state):
            return "Expand direct competitors"

    class MetricsScout:
        provider = "deepseek"
        model = "deepseek-chat"
        role_name = "scout_positioning"

        def run(self, state):
            self.last_tool_metrics = ToolExecutionMetrics(
                external_fetches=2,
                timings_ms={"search": 11, "github_lookup": 7},
                notes=["scout used normalized root URL"],
            )
            return [
                Candidate(
                    candidate_id="cand-aider-1",
                    name="Aider",
                    canonical_url="https://aider.chat",
                    status=CandidateStatus.DISCOVERED,
                    relevance_score=0.92,
                    why_candidate="terminal coding agent",
                )
            ]

    class MetricsAnalyst:
        provider = "deepseek"
        model = "deepseek-chat"
        role_name = "analyst_workflow"

        def run(self, state, candidate):
            self.last_tool_metrics = ToolExecutionMetrics(
                external_fetches=3,
                timings_ms={"page_extract": 19, "search": 5},
                notes=["fallback to search hit for candidate evidence"],
            )
            evidence = Evidence(
                evidence_id="e-aider-1",
                subject_id=candidate.candidate_id,
                claim="Aider supports terminal workflows",
                source_url="https://aider.chat",
                source_type="official",
                snippet="terminal workflow",
                captured_at="2026-04-02",
                freshness_score=0.95,
                confidence=0.91,
            )
            finding = Finding(
                finding_id="f-aider-1",
                subject_id=candidate.candidate_id,
                dimension="workflow",
                summary="Aider runs in terminal workflows.",
                evidence_ids=["e-aider-1"],
                confidence=0.91,
            )
            return [evidence], [finding], []

    class StopNow:
        def run(self, state):
            return StopDecision(verdict=StopVerdict.STOP, reasons=["done"], gap_tickets=[])

    controller = HarnessController(
        store=FileRunStore(tmp_path / "runs"),
        initializer=FakeInitializer(),
        lead_researcher=PassingLeadResearcher(),
        scouts=[MetricsScout()],
        analysts=[MetricsAnalyst()],
        compactor=ContextCompactor(),
        evidence_judge=lambda state: None,
        coverage_judge=lambda state: None,
        challenger=lambda state: None,
        stop_judge=StopNow(),
        clock=IncrementingClock(),
    )

    final_state = controller.run(
        target="Claude Code",
        budget=BudgetPolicy(
            max_rounds=4,
            max_active_candidates=8,
            max_deepen_targets=3,
            max_external_fetches=30,
            max_run_duration_minutes=20,
        ),
    )

    expand_trace = next(trace for trace in final_state.traces if trace.phase == Phase.EXPAND)
    deepen_trace = next(trace for trace in final_state.traces if trace.phase == Phase.DEEPEN)

    assert expand_trace.phase_duration_ms > 0
    assert deepen_trace.phase_duration_ms > 0
    assert expand_trace.role_timings_ms["lead_researcher"] > 0
    assert expand_trace.role_timings_ms["scout_positioning"] > 0
    assert deepen_trace.role_timings_ms["analyst_workflow"] > 0
    assert expand_trace.tool_timings_ms == {"search": 11, "github_lookup": 7}
    assert deepen_trace.tool_timings_ms == {"page_extract": 19, "search": 5}
    assert "scout used normalized root URL" in expand_trace.diagnostics
    assert "fallback to search hit for candidate evidence" in deepen_trace.diagnostics
    assert final_state.external_fetch_count == 5


def test_controller_stops_when_external_fetch_budget_is_exhausted(tmp_path: Path):
    from jingyantai.domain.models import Candidate
    from jingyantai.domain.phases import CandidateStatus

    class PassingLeadResearcher:
        role_name = "lead_researcher"

        def run(self, state):
            return "Expand direct competitors"

    class BudgetEatingScout:
        provider = "deepseek"
        model = "deepseek-chat"
        role_name = "scout_positioning"

        def run(self, state):
            self.last_tool_metrics = ToolExecutionMetrics(
                external_fetches=9,
                fetch_breakdown={"search": 6, "github_lookup": 3},
                timings_ms={"search": 10},
                notes=["expended search budget"],
            )
            return [
                Candidate(
                    candidate_id="cand-aider-1",
                    name="Aider",
                    canonical_url="https://aider.chat",
                    status=CandidateStatus.DISCOVERED,
                    relevance_score=0.92,
                    why_candidate="terminal coding agent",
                )
            ]

    controller = HarnessController(
        store=FileRunStore(tmp_path / "runs"),
        initializer=FakeInitializer(),
        lead_researcher=PassingLeadResearcher(),
        scouts=[BudgetEatingScout()],
        analysts=[],
        compactor=ContextCompactor(),
        evidence_judge=lambda state: None,
        coverage_judge=lambda state: None,
        challenger=lambda state: None,
        stop_judge=lambda state: None,
    )

    final_state = controller.run(
        target="Claude Code",
        budget=BudgetPolicy(
            max_rounds=4,
            max_active_candidates=8,
            max_deepen_targets=3,
            max_external_fetches=5,
            max_run_duration_minutes=20,
        ),
    )

    assert final_state.current_phase == Phase.STOP
    assert final_state.external_fetch_count == 9
    assert final_state.external_fetch_breakdown == {"search": 6, "github_lookup": 3}
    assert final_state.stop_reason is not None
    assert "external fetch budget exceeded" in final_state.stop_reason
    assert "search=6" in final_state.stop_reason
    assert "github_lookup=3" in final_state.stop_reason
    assert any("external fetch budget exceeded" in note for trace in final_state.traces for note in trace.diagnostics)

    log_path = tmp_path / "runs" / final_state.run_id / "artifacts" / "progress-log.jsonl"
    assert log_path.exists()
    records = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert any(
        isinstance(record.get("stop_reason"), str) and "external fetch budget exceeded" in record["stop_reason"]
        for record in records
    )
    assert any(
        isinstance(record.get("message"), str) and "external fetch budget exceeded" in record["message"]
        for record in records
    )

    evaluator_log_path = tmp_path / "runs" / final_state.run_id / "artifacts" / "evaluator-log.jsonl"
    assert evaluator_log_path.exists()
    evaluator_records = [
        json.loads(line) for line in evaluator_log_path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    assert any(
        record.get("event_type") == "forced_stop"
        and isinstance(record.get("stop_reason"), str)
        and "external fetch budget exceeded" in record["stop_reason"]
        for record in evaluator_records
    )


def test_controller_stops_when_run_duration_budget_is_exhausted(tmp_path: Path):
    class JumpingClock:
        def __init__(self) -> None:
            self.current = 0.0

        def __call__(self) -> float:
            self.current += 1.0
            return self.current

    controller = HarnessController(
        store=FileRunStore(tmp_path / "runs"),
        initializer=FakeInitializer(),
        lead_researcher=FakeLeadResearcher(),
        scouts=[],
        analysts=[],
        compactor=ContextCompactor(),
        evidence_judge=lambda state: None,
        coverage_judge=lambda state: None,
        challenger=lambda state: None,
        stop_judge=lambda state: None,
        clock=JumpingClock(),
    )

    final_state = controller.run(
        target="Claude Code",
        budget=BudgetPolicy(
            max_rounds=4,
            max_active_candidates=8,
            max_deepen_targets=3,
            max_external_fetches=30,
            max_run_duration_minutes=0,
        ),
    )

    assert final_state.current_phase == Phase.STOP
    assert final_state.stop_reason is not None
    assert "run duration budget exceeded" in final_state.stop_reason
    assert any("run duration budget exceeded" in note for trace in final_state.traces for note in trace.diagnostics)


def test_controller_emits_progress_events_for_phase_boundaries(tmp_path: Path):
    events = []

    class StopNow:
        def run(self, state):
            from jingyantai.domain.models import StopDecision

            return StopDecision(verdict=StopVerdict.STOP, reasons=["done"], gap_tickets=[])

    controller = HarnessController(
        store=FileRunStore(tmp_path / "runs"),
        initializer=FakeInitializer(),
        lead_researcher=FakeLeadResearcher(),
        scouts=[FakeScout("aider")],
        analysts=[FakeAnalyst()],
        compactor=ContextCompactor(),
        evidence_judge=lambda state: None,
        coverage_judge=lambda state: None,
        challenger=lambda state: None,
        stop_judge=StopNow(),
        progress_reporter=events.append,
    )

    controller.run(
        target="Claude Code",
        budget=BudgetPolicy(
            max_rounds=4,
            max_active_candidates=8,
            max_deepen_targets=3,
            max_external_fetches=30,
            max_run_duration_minutes=20,
        ),
    )

    phases = [(event.stage, event.phase) for event in events]
    assert ("start", Phase.INITIALIZE) in phases
    assert ("end", Phase.INITIALIZE) in phases
    assert ("start", Phase.EXPAND) in phases
    assert ("end", Phase.DEEPEN) in phases
    assert events[0].message == "starting phase"
    assert events[-1].phase == Phase.DECIDE


def test_controller_checkpoints_state_and_traces_during_run():
    class SpyStore:
        def __init__(self) -> None:
            self.saved_states = []
            self.saved_traces = []

        def save_state(self, state) -> None:
            self.saved_states.append((state.run_id, len(state.traces), state.current_phase))

        def append_trace(self, run_id, trace) -> None:
            self.saved_traces.append((run_id, trace.phase, trace.round_index))

    class StopNow:
        def run(self, state):
            from jingyantai.domain.models import StopDecision

            return StopDecision(verdict=StopVerdict.STOP, reasons=["done"], gap_tickets=[])

    store = SpyStore()
    controller = HarnessController(
        store=store,
        initializer=FakeInitializer(),
        lead_researcher=FakeLeadResearcher(),
        scouts=[FakeScout("aider")],
        analysts=[FakeAnalyst()],
        compactor=ContextCompactor(),
        evidence_judge=lambda state: None,
        coverage_judge=lambda state: None,
        challenger=lambda state: None,
        stop_judge=StopNow(),
    )

    final_state = controller.run(
        target="Claude Code",
        budget=BudgetPolicy(
            max_rounds=4,
            max_active_candidates=8,
            max_deepen_targets=3,
            max_external_fetches=30,
            max_run_duration_minutes=20,
        ),
    )

    assert len(store.saved_traces) == len(final_state.traces)
    assert len(store.saved_states) >= len(final_state.traces) + 1


def test_controller_persists_round_contract_and_progress_log(tmp_path: Path):
    from jingyantai.domain.phases import StopVerdict

    class FakeLeadResearcherForContract:
        def run(self, state):
            return "Resolve pricing uncertainty for top competitors."

    class FakeContractBuilder:
        def build(self, state):
            return RoundContract(
                target_scope="confirmed candidates",
                goal_cluster="resolve pricing uncertainty",
                must_answer_questions=["How is access exposed?"],
                required_evidence_types=["official"],
                hard_checks=["must cite official source"],
                done_definition="At least one pricing/access finding is produced.",
                fallback_plan="Keep unresolved issues as uncertainties.",
            )

    store = FileRunStore(tmp_path / "runs")
    controller = HarnessController(
        store=store,
        initializer=FakeInitializer(),
        lead_researcher=FakeLeadResearcherForContract(),
        scouts=[],
        analysts=[],
        compactor=ContextCompactor(),
        evidence_judge=lambda state: None,
        coverage_judge=lambda state: None,
        challenger=lambda state: None,
        stop_judge=lambda state: type(
            "StopNow", (), {"verdict": StopVerdict.STOP, "gap_tickets": [], "reasons": ["done"]}
        )(),
        contract_builder=FakeContractBuilder(),
    )

    final_state = controller.run(
        target="Claude Code",
        budget=BudgetPolicy(
            max_rounds=0,
            max_active_candidates=8,
            max_deepen_targets=3,
            max_external_fetches=30,
            max_run_duration_minutes=20,
        ),
    )

    run_dir = tmp_path / "runs" / final_state.run_id / "artifacts"
    assert (run_dir / "round-contract-000.json").exists()
    assert (run_dir / "progress-log.jsonl").exists()


def test_controller_persists_research_spec_artifact(tmp_path: Path):
    store = FileRunStore(tmp_path / "runs")
    controller = HarnessController(
        store=store,
        initializer=FakeInitializer(),
        lead_researcher=FakeLeadResearcher(),
        scouts=[],
        analysts=[],
        compactor=ContextCompactor(),
        evidence_judge=lambda state: None,
        coverage_judge=lambda state: None,
        challenger=lambda state: None,
        stop_judge=lambda state: type(
            "StopNow", (), {"verdict": StopVerdict.STOP, "gap_tickets": [], "reasons": ["done"]}
        )(),
    )

    final_state = controller.run(
        target="Claude Code",
        budget=BudgetPolicy(
            max_rounds=0,
            max_active_candidates=8,
            max_deepen_targets=3,
            max_external_fetches=30,
            max_run_duration_minutes=20,
        ),
    )

    research_spec_path = tmp_path / "runs" / final_state.run_id / "artifacts" / "research-spec.json"
    assert research_spec_path.exists()

    payload = json.loads(research_spec_path.read_text(encoding="utf-8"))
    assert payload["target"] == "Claude Code"
    assert payload["mission"] == "Research competitors for Claude Code"
    assert payload["product_type"] == "coding-agent"
    assert payload["required_dimensions"] == [
        "positioning",
        "workflow",
        "core capabilities",
        "pricing or access",
        "community / ecosystem signal",
    ]
    assert payload["budget"]["max_rounds"] == 0
    assert payload["quality_rubric"]["required_dimensions"] == [
        "positioning",
        "workflow",
        "pricing or access",
    ]


def test_controller_persists_evaluator_log_for_review_and_stop_decision(tmp_path: Path):
    from jingyantai.domain.models import ReviewDecision, StopDecision
    from jingyantai.domain.phases import ReviewVerdict

    def passing_review(judge_type: str) -> ReviewDecision:
        return ReviewDecision(
            judge_type=judge_type,
            target_scope="run",
            verdict=ReviewVerdict.PASS,
            reasons=[f"{judge_type} ok"],
            required_actions=[],
        )

    class StopNow:
        def run(self, state):
            return StopDecision(verdict=StopVerdict.STOP, reasons=["quality bar met"], gap_tickets=[])

    controller = HarnessController(
        store=FileRunStore(tmp_path / "runs"),
        initializer=FakeInitializer(),
        lead_researcher=FakeLeadResearcher(),
        scouts=[],
        analysts=[],
        compactor=ContextCompactor(),
        evidence_judge=lambda state: passing_review("evidence"),
        coverage_judge=lambda state: passing_review("coverage"),
        challenger=lambda state: passing_review("challenger"),
        stop_judge=StopNow(),
    )

    final_state = controller.run(
        target="Claude Code",
        budget=BudgetPolicy(
            max_rounds=0,
            max_active_candidates=8,
            max_deepen_targets=3,
            max_external_fetches=30,
            max_run_duration_minutes=20,
        ),
    )

    log_path = tmp_path / "runs" / final_state.run_id / "artifacts" / "evaluator-log.jsonl"
    assert log_path.exists()

    records = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    review_records = [record for record in records if record["event_type"] == "review_decision"]
    assert len(review_records) == 3
    assert {record["judge_type"] for record in review_records} == {"evidence", "coverage", "challenger"}
    assert all(record["verdict"] == "pass" for record in review_records)
    assert any(
        record["event_type"] == "stop_decision"
        and record["verdict"] == "stop"
        and record["reasons"] == ["quality bar met"]
        for record in records
    )


def test_controller_loads_memory_snapshot_into_carry_forward_context(tmp_path: Path):
    memory_store = FileMemoryStore(tmp_path / "runs")
    memory_store.save_snapshot(
        MemorySnapshot(
            top_competitors=["Legacy One"],
            unresolved_uncertainties=["Legacy pricing uncertainty"],
            trusted_sources=["https://legacy.example"],
            repeated_failure_patterns=["timeout: legacy docs"],
        )
    )
    captured = {}

    class CapturingLeadResearcher:
        def run(self, state):
            captured["carry_forward_context"] = state.carry_forward_context
            captured["memory_snapshot"] = state.memory_snapshot
            captured["watchlist"] = state.watchlist
            return "Use loaded memory snapshot."

    controller = HarnessController(
        store=FileRunStore(tmp_path / "runs"),
        memory_store=memory_store,
        initializer=FakeInitializer(),
        lead_researcher=CapturingLeadResearcher(),
        scouts=[],
        analysts=[],
        compactor=ContextCompactor(),
        evidence_judge=lambda state: None,
        coverage_judge=lambda state: None,
        challenger=lambda state: None,
        stop_judge=lambda state: type(
            "StopNow", (), {"verdict": StopVerdict.STOP, "gap_tickets": [], "reasons": ["done"]}
        )(),
    )

    controller.run(
        target="Claude Code",
        budget=BudgetPolicy(
            max_rounds=0,
            max_active_candidates=8,
            max_deepen_targets=3,
            max_external_fetches=30,
            max_run_duration_minutes=20,
        ),
    )

    assert "Legacy One" in captured["carry_forward_context"]
    assert "Legacy pricing uncertainty" in captured["carry_forward_context"]
    assert captured["memory_snapshot"]["top_competitors"] == ["Legacy One"]
    assert captured["watchlist"] == []


def test_controller_persists_memory_snapshot_and_watchlist_after_run(tmp_path: Path):
    from jingyantai.domain.models import Candidate, GapTicket, StopDecision
    from jingyantai.domain.phases import CandidateStatus, GapPriority

    class SingleScout:
        def run(self, state):
            return [
                Candidate(
                    candidate_id="cand-1",
                    name="Candidate 1",
                    canonical_url="https://cand-1.dev",
                    status=CandidateStatus.DISCOVERED,
                    relevance_score=0.9,
                    why_candidate="terminal coding agent",
                )
            ]

    class NeedsMoreResearchStopJudge:
        def run(self, state):
            return StopDecision(
                verdict=StopVerdict.CONTINUE,
                reasons=["Need one more workflow pass."],
                gap_tickets=[
                    GapTicket(
                        gap_type="coverage",
                        target_scope="Candidate 1",
                        blocking_reason="Missing workflow detail.",
                        owner_role="analyst",
                        acceptance_rule="Add one more workflow finding.",
                        deadline_round=state.round_index + 1,
                        priority=GapPriority.HIGH,
                    )
                ],
            )

    memory_store = FileMemoryStore(tmp_path / "runs")
    controller = HarnessController(
        store=FileRunStore(tmp_path / "runs"),
        memory_store=memory_store,
        initializer=FakeInitializer(),
        lead_researcher=FakeLeadResearcher(),
        scouts=[SingleScout()],
        analysts=[],
        compactor=ContextCompactor(),
        evidence_judge=lambda state: None,
        coverage_judge=lambda state: None,
        challenger=lambda state: None,
        stop_judge=NeedsMoreResearchStopJudge(),
    )

    final_state = controller.run(
        target="Claude Code",
        budget=BudgetPolicy(
            max_rounds=0,
            max_active_candidates=8,
            max_deepen_targets=3,
            max_external_fetches=30,
            max_run_duration_minutes=20,
        ),
    )

    snapshot = memory_store.load_snapshot()
    watchlist = memory_store.load_watchlist()

    assert snapshot.top_competitors == ["Candidate 1"]
    assert watchlist
    assert watchlist[0].entity_name == "Candidate 1"
    assert watchlist[0].canonical_url == "https://cand-1.dev"
    assert watchlist[0].last_seen_run_id == final_state.run_id


def test_controller_extracts_watchlist_and_memory_from_coverage_review_reasons(tmp_path: Path):
    from jingyantai.domain.models import Candidate, ReviewDecision, StopDecision
    from jingyantai.domain.phases import CandidateStatus, ReviewVerdict

    class SingleScout:
        def run(self, state):
            return [
                Candidate(
                    candidate_id="cand-1",
                    name="Candidate 1",
                    canonical_url="https://cand-1.dev",
                    status=CandidateStatus.DISCOVERED,
                    relevance_score=0.9,
                    why_candidate="terminal coding agent",
                )
            ]

    def coverage_fail(state):
        return ReviewDecision(
            judge_type="coverage",
            target_scope="run",
            verdict=ReviewVerdict.FAIL,
            reasons=["Candidate 1 missing: workflow, pricing or access"],
            required_actions=["cover missing dimensions"],
        )

    class StopNow:
        def run(self, state):
            return StopDecision(verdict=StopVerdict.STOP, reasons=["done"], gap_tickets=[])

    memory_store = FileMemoryStore(tmp_path / "runs")
    controller = HarnessController(
        store=FileRunStore(tmp_path / "runs"),
        memory_store=memory_store,
        initializer=FakeInitializer(),
        lead_researcher=FakeLeadResearcher(),
        scouts=[SingleScout()],
        analysts=[],
        compactor=ContextCompactor(),
        evidence_judge=lambda state: None,
        coverage_judge=coverage_fail,
        challenger=lambda state: None,
        stop_judge=StopNow(),
    )

    controller.run(
        target="Claude Code",
        budget=BudgetPolicy(
            max_rounds=0,
            max_active_candidates=8,
            max_deepen_targets=3,
            max_external_fetches=30,
            max_run_duration_minutes=20,
        ),
    )

    snapshot = memory_store.load_snapshot()
    watchlist = memory_store.load_watchlist()

    assert "Candidate 1 missing: workflow, pricing or access" in snapshot.unresolved_uncertainties
    assert watchlist
    assert watchlist[0].entity_name == "Candidate 1"
    assert watchlist[0].canonical_url == "https://cand-1.dev"
    assert watchlist[0].watch_reason == "Missing dimensions: workflow, pricing or access"
    assert watchlist[0].revisit_trigger == "Cover all required dimensions with direct evidence."


def test_controller_respects_phase_soft_timeout_and_skips_remaining_scouts(tmp_path: Path):
    from jingyantai.domain.models import Candidate, StopDecision
    from jingyantai.domain.phases import CandidateStatus

    class IncrementingClock:
        def __init__(self) -> None:
            self.current = 0.0

        def __call__(self) -> float:
            self.current += 0.001
            return self.current

    class CountingScout:
        provider = "deepseek"
        model = "deepseek-chat"

        def __init__(self, suffix: str) -> None:
            self.role_name = f"scout_{suffix}"
            self.calls = 0
            self.suffix = suffix

        def run(self, state):
            self.calls += 1
            return [
                Candidate(
                    candidate_id=f"cand-{self.suffix}",
                    name=f"Candidate {self.suffix}",
                    canonical_url=f"https://{self.suffix}.dev",
                    status=CandidateStatus.DISCOVERED,
                    relevance_score=0.9,
                    why_candidate="terminal coding agent",
                )
            ]

    class StopNow:
        def run(self, state):
            return StopDecision(verdict=StopVerdict.STOP, reasons=["done"], gap_tickets=[])

    scout_a = CountingScout("a")
    scout_b = CountingScout("b")
    runtime_policy = RuntimePolicy.default()
    runtime_policy.phase_policies["expand"] = PhasePolicy(
        soft_timeout_seconds=0.003,
        max_attempts=1,
        allow_partial_success=False,
        degrade_on=[DegradeAction.REDUCE_SEARCH_RESULTS],
    )

    controller = HarnessController(
        store=FileRunStore(tmp_path / "runs"),
        initializer=FakeInitializer(),
        lead_researcher=FakeLeadResearcher(),
        scouts=[scout_a, scout_b],
        analysts=[],
        compactor=ContextCompactor(),
        evidence_judge=lambda state: None,
        coverage_judge=lambda state: None,
        challenger=lambda state: None,
        stop_judge=StopNow(),
        clock=IncrementingClock(),
        runtime_policy=runtime_policy,
    )

    final_state = controller.run(
        target="Claude Code",
        budget=BudgetPolicy(
            max_rounds=0,
            max_active_candidates=8,
            max_deepen_targets=3,
            max_external_fetches=30,
            max_run_duration_minutes=20,
        ),
    )

    expand_trace = next(trace for trace in final_state.traces if trace.phase == Phase.EXPAND)

    assert scout_a.calls == 1
    assert scout_b.calls == 0
    assert len(final_state.candidates) == 1
    assert any("soft timeout exceeded for phase expand" in item for item in expand_trace.diagnostics)


def test_controller_passes_phase_deadline_into_tools_and_skips_late_fetches(tmp_path: Path):
    from jingyantai.domain.models import Candidate, StopDecision
    from jingyantai.domain.phases import CandidateStatus
    from jingyantai.tools.contracts import PageData, SearchHit
    from jingyantai.tools.research_tools import ResearchTools

    class ManualClock:
        def __init__(self) -> None:
            self.current = 0.0

        def __call__(self) -> float:
            return self.current

        def advance(self, delta: float) -> None:
            self.current += delta

    class RecordingSearchClient:
        def __init__(self, clock: ManualClock) -> None:
            self.clock = clock
            self.calls = 0
            self.timeouts: list[float | None] = []

        def search(self, query: str, max_results: int = 5, timeout_seconds: float | None = None):
            self.calls += 1
            self.timeouts.append(timeout_seconds)
            self.clock.advance(0.01)
            return [SearchHit(title="OpenCode", url="https://opencode.dev", snippet="terminal coding agent")]

    class RecordingPageExtractor:
        def __init__(self, clock: ManualClock) -> None:
            self.clock = clock
            self.calls = 0
            self.timeouts: list[float | None] = []

        def extract(self, url: str, timeout_seconds: float | None = None):
            self.calls += 1
            self.timeouts.append(timeout_seconds)
            if timeout_seconds is not None:
                self.clock.advance(timeout_seconds)
                raise TimeoutError(f"page extract timed out after {timeout_seconds:.3f}s")
            self.clock.advance(0.01)
            return PageData(url=url, title="title", text="text", excerpt="excerpt")

    class RecordingGitHubSignals:
        def __init__(self, clock: ManualClock) -> None:
            self.clock = clock
            self.calls = 0
            self.timeouts: list[float | None] = []

        def lookup(self, query: str, timeout_seconds: float | None = None):
            self.calls += 1
            self.timeouts.append(timeout_seconds)
            self.clock.advance(0.01)
            return []

    class ToolDrivenScout:
        provider = "deepseek"
        model = "deepseek-chat"
        role_name = "scout_tools"

        def __init__(self, tools: ResearchTools) -> None:
            self.tools = tools
            self.last_tool_metrics = None

        def run(self, state):
            candidates = self.tools.search_competitor_candidates(
                state.target,
                "terminal coding agent",
                ["web", "github"],
                max_results=5,
            )
            self.last_tool_metrics = self.tools.consume_last_metrics()
            return [
                Candidate(
                    candidate_id="cand-opencode",
                    name=str(candidates[0]["name"]),
                    canonical_url=str(candidates[0]["canonical_url"]),
                    status=CandidateStatus.DISCOVERED,
                    relevance_score=0.9,
                    why_candidate="terminal coding agent",
                )
            ]

    class StopNow:
        def run(self, state):
            return StopDecision(verdict=StopVerdict.STOP, reasons=["done"], gap_tickets=[])

    clock = ManualClock()
    search = RecordingSearchClient(clock)
    page = RecordingPageExtractor(clock)
    github = RecordingGitHubSignals(clock)
    runtime_policy = RuntimePolicy.default()
    runtime_policy.phase_policies["expand"] = PhasePolicy(
        soft_timeout_seconds=0.015,
        max_attempts=1,
        allow_partial_success=False,
        degrade_on=[DegradeAction.REDUCE_SEARCH_RESULTS],
    )

    controller = HarnessController(
        store=FileRunStore(tmp_path / "runs"),
        initializer=FakeInitializer(),
        lead_researcher=FakeLeadResearcher(),
        scouts=[ToolDrivenScout(ResearchTools(search, page, github, clock=clock))],
        analysts=[],
        compactor=ContextCompactor(),
        evidence_judge=lambda state: None,
        coverage_judge=lambda state: None,
        challenger=lambda state: None,
        stop_judge=StopNow(),
        clock=clock,
        runtime_policy=runtime_policy,
    )

    final_state = controller.run(
        target="Claude Code",
        budget=BudgetPolicy(
            max_rounds=0,
            max_active_candidates=8,
            max_deepen_targets=3,
            max_external_fetches=30,
            max_run_duration_minutes=20,
        ),
    )

    expand_trace = next(trace for trace in final_state.traces if trace.phase == Phase.EXPAND)

    assert search.calls == 1
    assert github.calls == 0
    assert search.timeouts[0] == 0.015
    assert page.timeouts and page.timeouts[0] is not None and page.timeouts[0] <= 0.0051
    assert any("phase runtime deadline exceeded before external fetch" in item for item in expand_trace.diagnostics)


def test_controller_passes_phase_deadline_into_lead_researcher_llm_invocation(tmp_path: Path):
    from jingyantai.domain.models import StopDecision

    class ManualClock:
        def __init__(self) -> None:
            self.current = 0.0

        def __call__(self) -> float:
            return self.current

        def advance(self, delta: float) -> None:
            self.current += delta

    class RecordingTimeoutRunner:
        def __init__(self, clock: ManualClock) -> None:
            self.clock = clock
            self.config = ProviderConfig(
                provider="deepseek",
                model="deepseek-chat",
                base_url="https://api.deepseek.com",
                api_key_env="DEEPSEEK_API_KEY",
                timeout_seconds=20.0,
                max_retries=1,
            )
            self.invocations: list[ModelInvocation] = []

        def run(self, invocation: ModelInvocation) -> dict[str, object]:
            self.invocations.append(invocation)
            if invocation.timeout_seconds is not None:
                self.clock.advance(invocation.timeout_seconds)
            raise TimeoutError("model timed out")

    class StopNow:
        def run(self, state):
            return StopDecision(verdict=StopVerdict.STOP, reasons=["done"], gap_tickets=[])

    clock = ManualClock()
    runtime_policy = RuntimePolicy.default()
    runtime_policy.phase_policies["expand"] = PhasePolicy(
        soft_timeout_seconds=0.015,
        max_attempts=1,
        allow_partial_success=False,
        degrade_on=[DegradeAction.REDUCE_SEARCH_RESULTS],
    )
    runner = RecordingTimeoutRunner(clock)
    lead = LeadResearcherRole(
        adapter=DeepagentsRoleAdapter(
            role_prompt="You are the Lead Researcher.",
            runner=runner,
            clock=clock,
        )
    )

    controller = HarnessController(
        store=FileRunStore(tmp_path / "runs"),
        initializer=FakeInitializer(),
        lead_researcher=lead,
        scouts=[],
        analysts=[],
        compactor=ContextCompactor(),
        evidence_judge=lambda state: None,
        coverage_judge=lambda state: None,
        challenger=lambda state: None,
        stop_judge=StopNow(),
        clock=clock,
        runtime_policy=runtime_policy,
    )

    final_state = controller.run(
        target="Claude Code",
        budget=BudgetPolicy(
            max_rounds=0,
            max_active_candidates=8,
            max_deepen_targets=3,
            max_external_fetches=30,
            max_run_duration_minutes=20,
        ),
    )

    expand_trace = next(trace for trace in final_state.traces if trace.phase == Phase.EXPAND)

    assert len(runner.invocations) == 1
    assert runner.invocations[0].timeout_seconds == 0.015
    assert "Expand and deepen direct competitors for Claude Code" in expand_trace.planner_output


def test_controller_caps_timeout_retries_when_phase_deadline_is_active(tmp_path: Path):
    from jingyantai.agents.schemas import ScoutOutput
    from jingyantai.domain.models import StopDecision

    class ManualClock:
        def __init__(self) -> None:
            self.current = 0.0

        def __call__(self) -> float:
            return self.current

        def advance(self, delta: float) -> None:
            self.current += delta

    class TimeoutRunner:
        def __init__(self, clock: ManualClock) -> None:
            self.clock = clock
            self.config = ProviderConfig(
                provider="deepseek",
                model="deepseek-chat",
                base_url="https://api.deepseek.com",
                api_key_env="DEEPSEEK_API_KEY",
                timeout_seconds=20.0,
                max_retries=1,
            )
            self.invocations: list[ModelInvocation] = []

        def run(self, invocation: ModelInvocation) -> dict[str, object]:
            self.invocations.append(invocation)
            if invocation.timeout_seconds is not None:
                self.clock.advance(invocation.timeout_seconds)
            raise TimeoutError("model timed out")

    class NoopLeadResearcher:
        role_name = "lead_researcher"

        def run(self, state):
            return "Plan next pass"

    class TimeoutScout:
        role_name = "scout_positioning"
        provider = "deepseek"
        model = "deepseek-chat"

        def __init__(self, adapter: DeepagentsRoleAdapter) -> None:
            self.adapter = adapter

        def run(self, state):
            self.adapter.run({"target": state.target}, ScoutOutput)
            return []

    class StopNow:
        def run(self, state):
            return StopDecision(verdict=StopVerdict.STOP, reasons=["done"], gap_tickets=[])

    clock = ManualClock()
    runtime_policy = RuntimePolicy.default()
    runtime_policy.phase_policies["expand"] = PhasePolicy(
        soft_timeout_seconds=12.0,
        max_attempts=3,
        allow_partial_success=False,
        degrade_on=[DegradeAction.REDUCE_SEARCH_RESULTS],
    )
    runner = TimeoutRunner(clock)

    controller = HarnessController(
        store=FileRunStore(tmp_path / "runs"),
        initializer=FakeInitializer(),
        lead_researcher=NoopLeadResearcher(),
        scouts=[
            TimeoutScout(
                DeepagentsRoleAdapter(
                    role_prompt="You are the Scout.",
                    runner=runner,
                    clock=clock,
                )
            )
        ],
        analysts=[],
        compactor=ContextCompactor(),
        evidence_judge=lambda state: None,
        coverage_judge=lambda state: None,
        challenger=lambda state: None,
        stop_judge=StopNow(),
        clock=clock,
        runtime_policy=runtime_policy,
    )

    final_state = controller.run(
        target="Claude Code",
        budget=BudgetPolicy(
            max_rounds=0,
            max_active_candidates=8,
            max_deepen_targets=3,
            max_external_fetches=30,
            max_run_duration_minutes=20,
        ),
    )

    expand_trace = next(trace for trace in final_state.traces if trace.phase == Phase.EXPAND)

    assert len(runner.invocations) == 2
    assert any("scout_positioning retrying after timeout (attempt 1)" in item for item in expand_trace.diagnostics)
    assert any("scout_positioning degraded after timeout (attempt 2)" in item for item in expand_trace.diagnostics)


def test_controller_splits_expand_budget_across_remaining_scouts(tmp_path: Path):
    from jingyantai.domain.models import Candidate, StopDecision
    from jingyantai.domain.phases import CandidateStatus

    class ManualClock:
        def __init__(self) -> None:
            self.current = 0.0

        def __call__(self) -> float:
            return self.current

        def advance(self, delta: float) -> None:
            self.current += delta

    class SlowLeadResearcher:
        role_name = "lead_researcher"

        def __init__(self, clock: ManualClock) -> None:
            self.clock = clock

        def run(self, state):
            self.clock.advance(6.0)
            return "Plan next pass"

    class BudgetAwareScout:
        provider = "deepseek"
        model = "deepseek-chat"

        def __init__(self, suffix: str, clock: ManualClock) -> None:
            self.role_name = f"scout_{suffix}"
            self.clock = clock
            self.suffix = suffix
            self.calls = 0
            self._runtime_deadline_at: float | None = None
            self.assigned_budgets: list[float] = []

        def set_runtime_deadline(self, deadline_at: float | None) -> None:
            self._runtime_deadline_at = deadline_at
            if deadline_at is not None:
                self.assigned_budgets.append(deadline_at - self.clock())

        def clear_runtime_deadline(self) -> None:
            self._runtime_deadline_at = None

        def run(self, state):
            self.calls += 1
            if self._runtime_deadline_at is not None:
                # Simulate a role that uses its full assigned budget plus a small tail cost.
                self.clock.advance(max(self._runtime_deadline_at - self.clock(), 0.0) + 0.1)
            return [
                Candidate(
                    candidate_id=f"cand-{self.suffix}",
                    name=f"Candidate {self.suffix}",
                    canonical_url=f"https://{self.suffix}.dev",
                    status=CandidateStatus.DISCOVERED,
                    relevance_score=0.9,
                    why_candidate="terminal coding agent",
                )
            ]

    class StopNow:
        def run(self, state):
            return StopDecision(verdict=StopVerdict.STOP, reasons=["done"], gap_tickets=[])

    clock = ManualClock()
    scout_a = BudgetAwareScout("a", clock)
    scout_b = BudgetAwareScout("b", clock)
    runtime_policy = RuntimePolicy.default()
    runtime_policy.phase_policies["expand"] = PhasePolicy(
        soft_timeout_seconds=30.0,
        max_attempts=1,
        allow_partial_success=False,
        degrade_on=[DegradeAction.REDUCE_SEARCH_RESULTS],
    )

    controller = HarnessController(
        store=FileRunStore(tmp_path / "runs"),
        initializer=FakeInitializer(),
        lead_researcher=SlowLeadResearcher(clock),
        scouts=[scout_a, scout_b],
        analysts=[],
        compactor=ContextCompactor(),
        evidence_judge=lambda state: None,
        coverage_judge=lambda state: None,
        challenger=lambda state: None,
        stop_judge=StopNow(),
        clock=clock,
        runtime_policy=runtime_policy,
    )

    final_state = controller.run(
        target="Claude Code",
        budget=BudgetPolicy(
            max_rounds=0,
            max_active_candidates=8,
            max_deepen_targets=3,
            max_external_fetches=30,
            max_run_duration_minutes=20,
        ),
    )

    assert scout_a.assigned_budgets == [pytest.approx(12.0)]
    assert scout_a.calls == 1
    assert scout_b.calls == 1
    assert [candidate.name for candidate in final_state.candidates] == ["Candidate a", "Candidate b"]


def test_controller_splits_deepen_budget_across_remaining_analyst_runs(tmp_path: Path):
    from jingyantai.domain.models import Candidate, StopDecision
    from jingyantai.domain.phases import CandidateStatus

    class ManualClock:
        def __init__(self) -> None:
            self.current = 0.0

        def __call__(self) -> float:
            return self.current

        def advance(self, delta: float) -> None:
            self.current += delta

    class SingleScout:
        role_name = "scout_single"

        def run(self, state):
            return [
                Candidate(
                    candidate_id="cand-a",
                    name="Candidate a",
                    canonical_url="https://a.dev",
                    status=CandidateStatus.DISCOVERED,
                    relevance_score=0.9,
                    why_candidate="terminal coding agent",
                )
            ]

    class BudgetAwareAnalyst:
        def __init__(self, suffix: str, clock: ManualClock) -> None:
            self.role_name = f"analyst_{suffix}"
            self.clock = clock
            self.calls = 0
            self._runtime_deadline_at: float | None = None
            self.assigned_budgets: list[float] = []

        def set_runtime_deadline(self, deadline_at: float | None) -> None:
            self._runtime_deadline_at = deadline_at
            if deadline_at is not None:
                self.assigned_budgets.append(deadline_at - self.clock())

        def clear_runtime_deadline(self) -> None:
            self._runtime_deadline_at = None

        def run(self, state, candidate):
            self.calls += 1
            if self._runtime_deadline_at is not None:
                self.clock.advance(max(self._runtime_deadline_at - self.clock(), 0.0) + 0.1)
            return [], [], []

    class StopNow:
        def run(self, state):
            return StopDecision(verdict=StopVerdict.STOP, reasons=["done"], gap_tickets=[])

    clock = ManualClock()
    analyst_a = BudgetAwareAnalyst("a", clock)
    analyst_b = BudgetAwareAnalyst("b", clock)
    runtime_policy = RuntimePolicy.default()
    runtime_policy.phase_policies["deepen"] = PhasePolicy(
        soft_timeout_seconds=20.0,
        max_attempts=1,
        allow_partial_success=True,
        degrade_on=[DegradeAction.REDUCE_DEEPEN_TARGETS],
    )

    controller = HarnessController(
        store=FileRunStore(tmp_path / "runs"),
        initializer=FakeInitializer(),
        lead_researcher=FakeLeadResearcher(),
        scouts=[SingleScout()],
        analysts=[analyst_a, analyst_b],
        compactor=ContextCompactor(),
        evidence_judge=lambda state: None,
        coverage_judge=lambda state: None,
        challenger=lambda state: None,
        stop_judge=StopNow(),
        clock=clock,
        runtime_policy=runtime_policy,
    )

    controller.run(
        target="Claude Code",
        budget=BudgetPolicy(
            max_rounds=0,
            max_active_candidates=8,
            max_deepen_targets=3,
            max_external_fetches=30,
            max_run_duration_minutes=20,
        ),
    )

    assert analyst_a.assigned_budgets == [pytest.approx(10.0)]
    assert analyst_a.calls == 1
    assert analyst_b.calls == 1


def test_controller_preserves_tool_metrics_across_role_retries(tmp_path: Path):
    from jingyantai.domain.models import StopDecision

    class RetryingScout:
        provider = "deepseek"
        model = "deepseek-chat"
        role_name = "scout_positioning"

        def __init__(self) -> None:
            self.calls = 0
            self._runtime_deadline_at: float | None = None
            self.last_tool_metrics = None

        def set_runtime_deadline(self, deadline_at: float | None) -> None:
            self._runtime_deadline_at = deadline_at

        def clear_runtime_deadline(self) -> None:
            self._runtime_deadline_at = None

        def run(self, state):
            self.calls += 1
            if self.calls == 1:
                self.last_tool_metrics = ToolExecutionMetrics(
                    external_fetches=2,
                    fetch_breakdown={"search": 1, "page_extract": 1},
                    timings_ms={"search": 120, "page_extract": 240},
                    notes=["attempt1 metrics"],
                )
                raise TimeoutError("first attempt timed out")

            self.last_tool_metrics = ToolExecutionMetrics(
                external_fetches=0,
                fetch_breakdown={},
                timings_ms={},
                notes=["attempt2 metrics"],
            )
            raise TimeoutError("second attempt timed out")

    class StopNow:
        def run(self, state):
            return StopDecision(verdict=StopVerdict.STOP, reasons=["done"], gap_tickets=[])

    runtime_policy = RuntimePolicy.default()
    runtime_policy.phase_policies["expand"] = PhasePolicy(
        soft_timeout_seconds=30.0,
        max_attempts=2,
        allow_partial_success=False,
        degrade_on=[DegradeAction.REDUCE_SEARCH_RESULTS],
    )

    controller = HarnessController(
        store=FileRunStore(tmp_path / "runs"),
        initializer=FakeInitializer(),
        lead_researcher=FakeLeadResearcher(),
        scouts=[RetryingScout()],
        analysts=[],
        compactor=ContextCompactor(),
        evidence_judge=lambda state: None,
        coverage_judge=lambda state: None,
        challenger=lambda state: None,
        stop_judge=StopNow(),
        runtime_policy=runtime_policy,
    )

    final_state = controller.run(
        target="Claude Code",
        budget=BudgetPolicy(
            max_rounds=0,
            max_active_candidates=8,
            max_deepen_targets=3,
            max_external_fetches=30,
            max_run_duration_minutes=20,
        ),
    )

    expand_trace = next(trace for trace in final_state.traces if trace.phase == Phase.EXPAND)

    assert final_state.external_fetch_count == 2
    assert final_state.external_fetch_breakdown == {"search": 1, "page_extract": 1}
    assert expand_trace.tool_timings_ms == {"search": 120, "page_extract": 240}
    assert "attempt1 metrics" in expand_trace.diagnostics
    assert "attempt2 metrics" in expand_trace.diagnostics


def test_controller_persists_memory_json_after_run(tmp_path: Path):
    from jingyantai.domain.models import Candidate, StopDecision, UncertaintyItem
    from jingyantai.domain.phases import CandidateStatus

    class SingleScout:
        def run(self, state):
            return [
                Candidate(
                    candidate_id="cand-1",
                    name="Candidate 1",
                    canonical_url="https://cand-1.dev",
                    status=CandidateStatus.DISCOVERED,
                    relevance_score=0.9,
                    why_candidate="terminal coding agent",
                )
            ]

    class AnalystWithUncertainty:
        def run(self, state, candidate):
            from jingyantai.domain.models import Evidence, Finding

            evidence = Evidence(
                evidence_id="e-cand-1",
                subject_id=candidate.candidate_id,
                claim="Candidate 1 overlaps on workflow",
                source_url="https://cand-1.dev/pricing",
                source_type="official",
                snippet="workflow/pricing signal",
                captured_at="2026-04-03",
                freshness_score=0.9,
                confidence=0.9,
            )
            finding = Finding(
                finding_id="f-cand-1",
                subject_id=candidate.candidate_id,
                dimension="workflow",
                summary="Candidate 1 supports workflow overlap",
                evidence_ids=[evidence.evidence_id],
                confidence=0.9,
            )
            uncertainty = UncertaintyItem(
                statement="Pricing tier boundaries remain unclear.",
                impact="high",
                resolvability="medium",
                required_evidence="official pricing page snapshot",
                owner_role="analyst",
            )
            return [evidence], [finding], [uncertainty]

    class StopNow:
        def run(self, state):
            return StopDecision(verdict=StopVerdict.STOP, reasons=["done"], gap_tickets=[])

    memory_store = FileMemoryStore(tmp_path / "runs")
    controller = HarnessController(
        store=FileRunStore(tmp_path / "runs"),
        memory_store=memory_store,
        initializer=FakeInitializer(),
        lead_researcher=FakeLeadResearcher(),
        scouts=[SingleScout()],
        analysts=[AnalystWithUncertainty()],
        compactor=ContextCompactor(),
        evidence_judge=lambda state: None,
        coverage_judge=lambda state: None,
        challenger=lambda state: None,
        stop_judge=StopNow(),
    )

    final_state = controller.run(
        target="Claude Code",
        budget=BudgetPolicy(
            max_rounds=0,
            max_active_candidates=8,
            max_deepen_targets=1,
            max_external_fetches=30,
            max_run_duration_minutes=20,
        ),
    )

    entries = memory_store.load_memory()

    assert len(entries) == 1
    assert entries[0].run_id == final_state.run_id
    assert entries[0].target == "Claude Code"
    assert entries[0].confirmed_entities == ["Candidate 1"]
    assert entries[0].unresolved_uncertainties == ["Pricing tier boundaries remain unclear."]
    assert entries[0].trusted_sources == ["https://cand-1.dev/pricing"]


def test_controller_review_decisions_are_round_scoped_and_can_stop_after_warning_cleared(tmp_path: Path):
    """Regression: historical FAIL/WARN must not permanently block STOP once cleared in later rounds."""

    from jingyantai.domain.models import ReviewDecision
    from jingyantai.domain.phases import ReviewVerdict
    from jingyantai.runtime.judges import StopJudge
    from jingyantai.runtime.policies import StopBar

    class SequentialEvidenceJudge:
        def __init__(self, verdicts: list[ReviewVerdict]) -> None:
            self.verdicts = verdicts
            self.calls = 0

        def run(self, state):
            verdict = self.verdicts[min(self.calls, len(self.verdicts) - 1)]
            self.calls += 1
            required_actions = ["Resolve evidence warning."] if verdict != ReviewVerdict.PASS else []
            return ReviewDecision(
                judge_type="evidence",
                target_scope="run",
                verdict=verdict,
                reasons=[f"evidence verdict: {verdict.value}"],
                required_actions=required_actions,
            )

    class PassingJudge:
        def __init__(self, judge_type: str) -> None:
            self.judge_type = judge_type

        def run(self, state):
            return ReviewDecision(
                judge_type=self.judge_type,
                target_scope="run",
                verdict=ReviewVerdict.PASS,
                reasons=["pass"],
                required_actions=[],
            )

    store = FileRunStore(tmp_path / "runs")
    evidence_judge = SequentialEvidenceJudge([ReviewVerdict.WARN, ReviewVerdict.PASS])
    controller = HarnessController(
        store=store,
        initializer=FakeInitializer(),
        lead_researcher=FakeLeadResearcher(),
        scouts=[FakeScout("aider")],
        analysts=[FakeAnalyst()],
        compactor=ContextCompactor(),
        evidence_judge=evidence_judge,
        coverage_judge=PassingJudge("coverage"),
        challenger=PassingJudge("challenger"),
        stop_judge=StopJudge(required_dimensions=["positioning"], stop_bar=StopBar(min_confirmed_candidates=1)),
    )

    final_state = controller.run(
        target="Claude Code",
        budget=BudgetPolicy(
            max_rounds=4,
            max_active_candidates=8,
            max_deepen_targets=3,
            max_external_fetches=30,
            max_run_duration_minutes=20,
        ),
    )

    assert evidence_judge.calls >= 2
    assert final_state.current_phase == Phase.STOP
    # With round-scoped review_decisions, the run should STOP on round_index==1 (i.e., after two rounds).
    assert final_state.round_index == 1


def test_controller_re_expands_after_stopjudge_hard_gate_fail(tmp_path: Path):
    """Regression: StopJudge hard gate fail (confirmed < min) returns CONTINUE with no scout gaps,
    but controller must still EXPAND again in the next round to discover more candidates.
    """

    from jingyantai.domain.models import Candidate
    from jingyantai.domain.phases import CandidateStatus
    from jingyantai.runtime.judges import StopJudge
    from jingyantai.runtime.policies import StopBar

    class IncrementingScout:
        def __init__(self) -> None:
            self.calls = 0

        def run(self, state):
            self.calls += 1
            suffix = str(self.calls)
            return [
                Candidate(
                    candidate_id=f"cand-{suffix}",
                    name=f"Candidate {suffix}",
                    canonical_url=f"https://cand-{suffix}.dev",
                    status=CandidateStatus.DISCOVERED,
                    relevance_score=0.9,
                    why_candidate="terminal coding agent",
                )
            ]

    scout = IncrementingScout()
    controller = HarnessController(
        store=FileRunStore(tmp_path / "runs"),
        initializer=FakeInitializer(),
        lead_researcher=FakeLeadResearcher(),
        scouts=[scout],
        analysts=[],
        compactor=ContextCompactor(),
        evidence_judge=lambda state: None,
        coverage_judge=lambda state: None,
        challenger=lambda state: None,
        stop_judge=StopJudge(required_dimensions=[], stop_bar=StopBar(min_confirmed_candidates=2)),
    )

    final_state = controller.run(
        target="Claude Code",
        budget=BudgetPolicy(
            max_rounds=1,
            max_active_candidates=8,
            max_deepen_targets=3,
            max_external_fetches=30,
            max_run_duration_minutes=20,
        ),
    )

    expand_traces = [trace for trace in final_state.traces if trace.phase == Phase.EXPAND]
    assert scout.calls == 2
    assert len(expand_traces) == 2
    assert len(final_state.candidates) == 2


def test_controller_trace_new_fields_are_phase_scoped_not_cumulative(tmp_path: Path):
    """RunTrace fields named 'new_*' (and review_decisions) should reflect per-phase delta, not full snapshot."""

    from jingyantai.domain.models import ReviewDecision
    from jingyantai.domain.phases import ReviewVerdict
    from jingyantai.runtime.judges import StopJudge
    from jingyantai.runtime.policies import StopBar

    class IncrementingScout:
        def __init__(self) -> None:
            self.calls = 0

        def run(self, state):
            from jingyantai.domain.models import Candidate
            from jingyantai.domain.phases import CandidateStatus

            self.calls += 1
            suffix = str(self.calls)
            score = 0.8 if suffix == "1" else 0.9
            return [
                Candidate(
                    candidate_id=f"cand-{suffix}",
                    name=f"Candidate {suffix}",
                    canonical_url=f"https://cand-{suffix}.dev",
                    status=CandidateStatus.DISCOVERED,
                    relevance_score=score,
                    why_candidate="terminal coding agent",
                )
            ]

    class SimpleAnalyst:
        def run(self, state, candidate):
            from jingyantai.domain.models import Evidence, Finding

            evidence = Evidence(
                evidence_id=f"e-{candidate.candidate_id}",
                subject_id=candidate.candidate_id,
                claim="evidence",
                source_url=candidate.canonical_url,
                source_type="official",
                snippet="snippet",
                captured_at="2026-04-02",
                freshness_score=0.95,
                confidence=0.95,
            )
            finding = Finding(
                finding_id=f"f-{candidate.candidate_id}",
                subject_id=candidate.candidate_id,
                dimension="positioning",
                summary="summary",
                evidence_ids=[evidence.evidence_id],
                confidence=0.95,
            )
            return [evidence], [finding], []

    def passing_review(judge_type: str):
        return ReviewDecision(
            judge_type=judge_type,
            target_scope="run",
            verdict=ReviewVerdict.PASS,
            reasons=["pass"],
            required_actions=[],
        )

    controller = HarnessController(
        store=FileRunStore(tmp_path / "runs"),
        initializer=FakeInitializer(),
        lead_researcher=FakeLeadResearcher(),
        scouts=[IncrementingScout()],
        analysts=[SimpleAnalyst()],
        compactor=ContextCompactor(),
        evidence_judge=lambda state: passing_review("evidence"),
        coverage_judge=lambda state: passing_review("coverage"),
        challenger=lambda state: passing_review("challenger"),
        stop_judge=StopJudge(required_dimensions=[], stop_bar=StopBar(min_confirmed_candidates=2)),
    )

    final_state = controller.run(
        target="Claude Code",
        budget=BudgetPolicy(
            max_rounds=1,
            max_active_candidates=8,
            max_deepen_targets=1,
            max_external_fetches=30,
            max_run_duration_minutes=20,
        ),
    )

    def trace_for(phase: Phase, round_index: int):
        return next(t for t in final_state.traces if t.phase == phase and t.round_index == round_index)

    expand0 = trace_for(Phase.EXPAND, 0)
    deepen0 = trace_for(Phase.DEEPEN, 0)
    challenge0 = trace_for(Phase.CHALLENGE, 0)
    expand1 = trace_for(Phase.EXPAND, 1)
    deepen1 = trace_for(Phase.DEEPEN, 1)

    assert expand0.new_candidates == ["Candidate 1"]
    assert expand1.new_candidates == ["Candidate 2"]
    assert deepen0.new_findings == ["f-cand-1"]
    assert deepen1.new_findings == ["f-cand-2"]

    assert expand1.review_decisions == []
    assert challenge0.review_decisions == ["evidence", "coverage", "challenger"]


def test_controller_contract_is_validated_before_persisting_round_contract(tmp_path: Path):
    """Invalid contracts must not be silently persisted as artifacts."""

    import pytest

    from jingyantai.runtime.contracts import RoundContract

    class InvalidContractBuilder:
        def build(self, state):
            return RoundContract(
                target_scope="confirmed candidates",
                goal_cluster="resolve pricing uncertainty",
                must_answer_questions=["How is access exposed?"],
                required_evidence_types=["official"],
                hard_checks=[],
                done_definition="At least one pricing/access finding is produced.",
                fallback_plan="Keep unresolved issues as uncertainties.",
            )

    store = FileRunStore(tmp_path / "runs")

    class StopNow:
        def run(self, state):
            from jingyantai.domain.models import StopDecision

            return StopDecision(verdict=StopVerdict.STOP, reasons=["done"], gap_tickets=[])

    controller = HarnessController(
        store=store,
        initializer=FakeInitializer(),
        lead_researcher=FakeLeadResearcher(),
        scouts=[],
        analysts=[],
        compactor=ContextCompactor(),
        evidence_judge=lambda state: None,
        coverage_judge=lambda state: None,
        challenger=lambda state: None,
        stop_judge=StopNow(),
        contract_builder=InvalidContractBuilder(),
    )

    with pytest.raises(ValueError, match="RoundContract"):
        controller.run(
            target="Claude Code",
            budget=BudgetPolicy(
                max_rounds=0,
                max_active_candidates=8,
                max_deepen_targets=3,
                max_external_fetches=30,
                max_run_duration_minutes=20,
            ),
        )

    run_dirs = [path for path in (tmp_path / "runs").iterdir() if path.is_dir()]
    assert len(run_dirs) == 1
    assert not (run_dirs[0] / "artifacts" / "round-contract-000.json").exists()
    evaluator_log_path = run_dirs[0] / "artifacts" / "evaluator-log.jsonl"
    assert evaluator_log_path.exists()
    records = [json.loads(line) for line in evaluator_log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert any(
        record["event_type"] == "contract_rejected"
        and record["judge_type"] == "contract"
        and any("hard check" in reason.lower() for reason in record["reasons"])
        for record in records
    )


def test_controller_hydrates_historical_memory_and_preserves_snapshot_context(tmp_path: Path):
    captured: dict[str, object] = {}

    class CapturingLeadResearcher:
        role_name = "lead_researcher"

        def run(self, state):
            captured["carry_forward_context"] = state.carry_forward_context
            captured["historical_memory"] = getattr(state, "historical_memory", {})
            return "Use historical memory"

    class StopNow:
        def run(self, state):
            from jingyantai.domain.models import StopDecision

            return StopDecision(verdict=StopVerdict.STOP, reasons=["done"], gap_tickets=[])

    runs_dir = tmp_path / "runs"
    memory_store = FileMemoryStore(runs_dir)
    memory_store.save_snapshot(
        MemorySnapshot(
            top_competitors=["Legacy One"],
            unresolved_uncertainties=["Legacy pricing unclear"],
            trusted_sources=["https://legacy.example/pricing"],
            repeated_failure_patterns=["timeout on docs page"],
        )
    )
    memory_store.save_memory(
        [
            RunMemoryEntry(
                run_id="run-prev-1",
                target="Claude Code",
                confirmed_entities=["Aider"],
                unresolved_uncertainties=["Pricing unclear"],
                trusted_sources=["https://aider.chat"],
                repeated_failure_patterns=["timeout on pricing page"],
            ),
            RunMemoryEntry(
                run_id="run-prev-2",
                target="Other Target",
                confirmed_entities=["Unrelated"],
                unresolved_uncertainties=["Other uncertainty"],
                trusted_sources=["https://other.example"],
                repeated_failure_patterns=["other failure"],
            ),
        ]
    )

    controller = HarnessController(
        store=FileRunStore(runs_dir),
        initializer=FakeInitializer(),
        lead_researcher=CapturingLeadResearcher(),
        scouts=[],
        analysts=[],
        compactor=ContextCompactor(),
        evidence_judge=lambda state: None,
        coverage_judge=lambda state: None,
        challenger=lambda state: None,
        stop_judge=StopNow(),
    )

    controller.run(
        target="Claude Code",
        budget=BudgetPolicy(
            max_rounds=1,
            max_active_candidates=8,
            max_deepen_targets=3,
            max_external_fetches=30,
            max_run_duration_minutes=20,
        ),
    )

    assert "Legacy One" in str(captured["carry_forward_context"])
    assert captured["historical_memory"]["recent_runs"] == [
        {
            "run_id": "run-prev-1",
            "target": "Claude Code",
            "confirmed_entities": ["Aider"],
            "unresolved_uncertainties": ["Pricing unclear"],
            "trusted_sources": ["https://aider.chat"],
            "repeated_failure_patterns": ["timeout on pricing page"],
        }
    ]
    assert captured["historical_memory"]["recurring_competitors"] == ["Aider"]
    assert captured["historical_memory"]["recurring_trusted_sources"] == ["https://aider.chat"]


def test_controller_resume_continues_from_saved_resume_phase(tmp_path: Path):
    from jingyantai.domain.models import Candidate, Evidence, Finding, StopDecision
    from jingyantai.domain.phases import CandidateStatus
    from jingyantai.storage.run_store import FileRunStore

    class ResumeAnalyst:
        role_name = "analyst_workflow"

        def run(self, state, candidate):
            evidence = Evidence(
                evidence_id="e-aider-1",
                subject_id=candidate.candidate_id,
                claim="Aider supports terminal workflows",
                source_url="https://aider.chat",
                source_type="official",
                snippet="terminal workflow",
                captured_at="2026-04-06",
                freshness_score=0.95,
                confidence=0.9,
            )
            finding = Finding(
                finding_id="f-aider-1",
                subject_id=candidate.candidate_id,
                dimension="workflow",
                summary="Aider overlaps on workflow.",
                evidence_ids=["e-aider-1"],
                confidence=0.9,
            )
            return [evidence], [finding], []

    class StopNow:
        def run(self, state):
            return StopDecision(verdict=StopVerdict.STOP, reasons=["done"], gap_tickets=[])

    store = FileRunStore(tmp_path / "runs")
    brief, charter = FakeInitializer().run("Claude Code")
    budget = BudgetPolicy(
        max_rounds=4,
        max_active_candidates=8,
        max_deepen_targets=1,
        max_external_fetches=30,
        max_run_duration_minutes=20,
    )
    saved_state = RunState(
        run_id="run-resume",
        target="Claude Code",
        current_phase=Phase.DEEPEN,
        resume_phase=Phase.DEEPEN,
        resume_round_index=0,
        budget=budget,
        brief=brief,
        charter=charter,
        candidates=[
            Candidate(
                candidate_id="cand-aider-1",
                name="Aider",
                canonical_url="https://aider.chat",
                status=CandidateStatus.CONFIRMED,
                relevance_score=0.9,
                why_candidate="terminal coding agent",
            )
        ],
    )
    store.save_state(saved_state)

    controller = HarnessController(
        store=store,
        initializer=FakeInitializer(),
        lead_researcher=FakeLeadResearcher(),
        scouts=[],
        analysts=[ResumeAnalyst()],
        compactor=ContextCompactor(),
        evidence_judge=lambda state: None,
        coverage_judge=lambda state: None,
        challenger=lambda state: None,
        stop_judge=StopNow(),
    )

    final_state = controller.resume(run_id="run-resume", budget=saved_state.budget)

    assert final_state.run_id == "run-resume"
    assert final_state.current_phase == Phase.STOP
    assert any(finding.finding_id == "f-aider-1" for finding in final_state.findings)


def test_controller_resume_stops_when_cancel_is_requested(tmp_path: Path):
    from jingyantai.domain.models import StopDecision
    from jingyantai.storage.run_store import FileRunStore

    class ShouldNotRunLead:
        def run(self, state):
            raise AssertionError("resume should stop before invoking roles")

    store = FileRunStore(tmp_path / "runs")
    brief, charter = FakeInitializer().run("Claude Code")
    budget = BudgetPolicy(
        max_rounds=4,
        max_active_candidates=8,
        max_deepen_targets=1,
        max_external_fetches=30,
        max_run_duration_minutes=20,
    )
    saved_state = RunState(
        run_id="run-cancel",
        target="Claude Code",
        current_phase=Phase.EXPAND,
        resume_phase=Phase.EXPAND,
        resume_round_index=0,
        budget=budget,
        brief=brief,
        charter=charter,
    )
    store.save_state(saved_state)
    store.request_cancel("run-cancel", reason="cancelled by user")

    controller = HarnessController(
        store=store,
        initializer=FakeInitializer(),
        lead_researcher=ShouldNotRunLead(),
        scouts=[],
        analysts=[],
        compactor=ContextCompactor(),
        evidence_judge=lambda state: None,
        coverage_judge=lambda state: None,
        challenger=lambda state: None,
        stop_judge=lambda state: StopDecision(verdict=StopVerdict.STOP, reasons=["done"], gap_tickets=[]),
    )

    final_state = controller.resume(run_id="run-cancel", budget=budget)

    assert final_state.current_phase == Phase.STOP
    assert final_state.stop_reason == "cancelled by user"
