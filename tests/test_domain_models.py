import pytest

from jingyantai.domain.models import BudgetPolicy, Candidate, RunState
from jingyantai.domain.phases import CandidateStatus, Phase


def test_candidate_rejects_invalid_status_jump():
    candidate = Candidate(
        candidate_id="c1",
        name="OpenAI Codex CLI",
        canonical_url="https://openai.com",
        status=CandidateStatus.DISCOVERED,
        relevance_score=0.5,
        why_candidate="Terminal coding agent",
    )

    with pytest.raises(ValueError):
        candidate.transition_to(CandidateStatus.PRIORITIZED)


def test_run_state_returns_top_candidates_in_priority_order():
    state = RunState(
        run_id="run-1",
        target="Claude Code",
        current_phase=Phase.CONVERGE,
        budget=BudgetPolicy(max_rounds=4, max_active_candidates=8, max_deepen_targets=3, max_external_fetches=30, max_run_duration_minutes=20),
    )
    state.candidates.extend(
        [
            Candidate(candidate_id="a", name="A", canonical_url="https://a.dev", status=CandidateStatus.PRIORITIZED, relevance_score=0.6, why_candidate="A"),
            Candidate(candidate_id="b", name="B", canonical_url="https://b.dev", status=CandidateStatus.PRIORITIZED, relevance_score=0.9, why_candidate="B"),
            Candidate(candidate_id="c", name="C", canonical_url="https://c.dev", status=CandidateStatus.REJECTED, relevance_score=0.99, why_candidate="C"),
        ]
    )

    assert [candidate.name for candidate in state.top_candidates(limit=2)] == ["B", "A"]
