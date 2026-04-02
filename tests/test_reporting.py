from __future__ import annotations

from jingyantai.domain.models import BudgetPolicy, Candidate, Evidence, Finding, RunState
from jingyantai.domain.phases import CandidateStatus, Phase
from jingyantai.runtime.reporting import CitationAgent, Synthesizer


def test_synthesizer_and_citation_agent_build_cited_report():
    state = RunState(
        run_id="run-1",
        target="Claude Code",
        current_phase=Phase.STOP,
        budget=BudgetPolicy(
            max_rounds=4,
            max_active_candidates=8,
            max_deepen_targets=3,
            max_external_fetches=30,
            max_run_duration_minutes=20,
        ),
    )
    state.candidates.append(
        Candidate(
            candidate_id="a",
            name="Aider",
            canonical_url="https://aider.chat",
            status=CandidateStatus.CONFIRMED,
            relevance_score=0.93,
            why_candidate="terminal coding agent",
        )
    )
    state.evidence.append(
        Evidence(
            evidence_id="e1",
            subject_id="a",
            claim="Aider runs in the terminal",
            source_url="https://aider.chat",
            source_type="official",
            snippet="AI pair programmer in your terminal",
            captured_at="2026-04-01",
            freshness_score=0.95,
            confidence=0.95,
        )
    )
    state.findings.append(
        Finding(
            finding_id="f1",
            subject_id="a",
            dimension="workflow",
            summary="Aider overlaps with Claude Code in terminal workflow.",
            evidence_ids=["e1"],
            confidence=0.95,
        )
    )

    draft = Synthesizer().run(state)
    final = CitationAgent().run(state, draft)

    assert final.confirmed_competitors == ["Aider"]
    assert final.citations["Aider"] == ["https://aider.chat"]
