from __future__ import annotations

from pathlib import Path

from jingyantai.domain.models import BudgetPolicy
from jingyantai.domain.phases import StopVerdict
from jingyantai.runtime.compactor import ContextCompactor
from jingyantai.runtime.controller import HarnessController
from jingyantai.storage.run_store import FileRunStore
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
