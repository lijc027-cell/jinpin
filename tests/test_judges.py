from __future__ import annotations

from jingyantai.domain.models import BudgetPolicy, Candidate, Finding, ResearchBrief, RunState
from jingyantai.domain.phases import CandidateStatus, Phase, StopVerdict


def _minimal_budget() -> BudgetPolicy:
    return BudgetPolicy(
        max_rounds=4,
        max_active_candidates=8,
        max_deepen_targets=3,
        max_external_fetches=30,
        max_run_duration_minutes=20,
    )


def test_stop_judge_confirmed_candidate_missing_required_dimensions_continues_with_analyst_gap_ticket():
    from jingyantai.runtime.judges import StopJudge

    brief = ResearchBrief(
        target="Claude Code",
        product_type="coding-agent",
        competitor_definition="Direct competitors are terminal-native coding agents for software engineers.",
        required_dimensions=["workflow", "pricing"],
        stop_policy="Stop after enough confirmed competitors with coverage.",
        budget=_minimal_budget(),
    )
    state = RunState(
        run_id="run-1",
        target="Claude Code",
        current_phase=Phase.STOP,
        budget=_minimal_budget(),
        brief=brief,
        round_index=1,
    )
    state.candidates.append(
        Candidate(
            candidate_id="c1",
            name="Competitor One",
            canonical_url="https://c1.dev",
            status=CandidateStatus.CONFIRMED,
            relevance_score=0.9,
            why_candidate="direct",
        )
    )
    # Only one dimension covered; the other should trigger a gap ticket.
    state.findings.append(
        Finding(
            finding_id="f1",
            subject_id="c1",
            dimension="workflow",
            summary="Has an integrated terminal workflow.",
            evidence_ids=["e1"],
            confidence=0.8,
        )
    )

    decision = StopJudge().run(state)

    assert decision.verdict == StopVerdict.CONTINUE
    assert decision.gap_tickets
    assert any(ticket.owner_role == "analyst" for ticket in decision.gap_tickets)


def test_context_compactor_compact_includes_target_and_top_candidate_snapshot():
    from jingyantai.runtime.compactor import ContextCompactor

    state = RunState(
        run_id="run-1",
        target="Claude Code",
        current_phase=Phase.CONVERGE,
        budget=_minimal_budget(),
    )
    state.candidates.extend(
        [
            Candidate(
                candidate_id="c1",
                name="Lower",
                canonical_url="https://lower.dev",
                status=CandidateStatus.PRIORITIZED,
                relevance_score=0.4,
                why_candidate="lower score",
            ),
            Candidate(
                candidate_id="c2",
                name="Top",
                canonical_url="https://top.dev",
                status=CandidateStatus.PRIORITIZED,
                relevance_score=0.9,
                why_candidate="top score",
            ),
        ]
    )

    snapshot = ContextCompactor().compact(state)

    assert "Claude Code" in snapshot
    assert "Top" in snapshot
