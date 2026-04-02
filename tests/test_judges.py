from __future__ import annotations

from jingyantai.domain.models import (
    BudgetPolicy,
    Candidate,
    Evidence,
    Finding,
    OpenQuestion,
    ResearchBrief,
    ReviewDecision,
    RunState,
)
from jingyantai.domain.phases import CandidateStatus, GapPriority, Phase, ReviewVerdict, StopVerdict


def _minimal_budget() -> BudgetPolicy:
    return BudgetPolicy(
        max_rounds=4,
        max_active_candidates=8,
        max_deepen_targets=3,
        max_external_fetches=30,
        max_run_duration_minutes=20,
    )


def test_stop_judge_requires_required_dimensions_constructor_and_does_not_depend_on_brief():
    from jingyantai.runtime.judges import StopJudge

    brief = ResearchBrief(
        target="Claude Code",
        product_type="coding-agent",
        competitor_definition="Direct competitors are terminal-native coding agents for software engineers.",
        # Intentionally wrong: StopJudge must not depend on state.brief.required_dimensions.
        required_dimensions=["not-used"],
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

    decision = StopJudge(required_dimensions=["workflow", "pricing"]).run(state)

    assert decision.verdict == StopVerdict.CONTINUE
    assert decision.gap_tickets
    assert any(ticket.owner_role == "analyst" for ticket in decision.gap_tickets)


def test_stop_judge_does_not_count_finding_as_coverage_without_evidence():
    from jingyantai.runtime.judges import StopJudge

    state = RunState(
        run_id="run-1",
        target="Claude Code",
        current_phase=Phase.STOP,
        budget=_minimal_budget(),
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
    # Findings exist for all dimensions, but there is no evidence; must still CONTINUE.
    state.findings.extend(
        [
            Finding(
                finding_id="f1",
                subject_id="c1",
                dimension="workflow",
                summary="Workflow summary.",
                evidence_ids=["missing-e1"],
                confidence=0.8,
            ),
            Finding(
                finding_id="f2",
                subject_id="c1",
                dimension="pricing",
                summary="Pricing summary.",
                evidence_ids=["missing-e2"],
                confidence=0.8,
            ),
        ]
    )

    decision = StopJudge(required_dimensions=["workflow", "pricing"]).run(state)

    assert decision.verdict == StopVerdict.CONTINUE


def test_evidence_judge_fails_on_low_confidence_evidence():
    from jingyantai.runtime.judges import EvidenceJudge

    state = RunState(
        run_id="run-1",
        target="Claude Code",
        current_phase=Phase.DEEPEN,
        budget=_minimal_budget(),
        round_index=1,
    )
    state.evidence.append(
        Evidence(
            evidence_id="e1",
            subject_id="c1",
            claim="Supports a key workflow claim",
            source_url="https://example.com",
            source_type="web",
            snippet="snippet",
            captured_at="2026-04-02",
            freshness_score=0.5,
            confidence=0.59,
            supports_or_conflicts="supports",
        )
    )

    decision = EvidenceJudge().run(state)

    assert decision.judge_type == "evidence"
    assert decision.verdict == ReviewVerdict.FAIL


def test_stop_judge_adds_scout_gap_ticket_when_confirmed_below_threshold():
    from jingyantai.runtime.judges import StopJudge

    state = RunState(
        run_id="run-1",
        target="Claude Code",
        current_phase=Phase.STOP,
        budget=_minimal_budget(),
        round_index=1,
    )
    state.candidates.extend(
        [
            Candidate(
                candidate_id="c1",
                name="C1",
                canonical_url="https://c1.dev",
                status=CandidateStatus.CONFIRMED,
                relevance_score=0.9,
                why_candidate="direct",
            ),
            Candidate(
                candidate_id="c2",
                name="C2",
                canonical_url="https://c2.dev",
                status=CandidateStatus.CONFIRMED,
                relevance_score=0.8,
                why_candidate="direct",
            ),
        ]
    )

    decision = StopJudge(required_dimensions=["workflow"]).run(state)

    assert decision.verdict == StopVerdict.CONTINUE
    assert "Quality bar not met" in decision.reasons
    assert any(
        ticket.gap_type == "candidate_count"
        and ticket.target_scope == "run"
        and ticket.owner_role == "scout"
        and ticket.acceptance_rule == "Confirm at least 3 direct competitors."
        and ticket.blocking_reason == "Need at least 3 confirmed competitors."
        for ticket in decision.gap_tickets
    )


def test_coverage_judge_shape_and_required_actions_are_missing_list():
    from jingyantai.runtime.judges import CoverageJudge

    state = RunState(
        run_id="run-1",
        target="Claude Code",
        current_phase=Phase.DECIDE,
        budget=_minimal_budget(),
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
    state.evidence.append(
        Evidence(
            evidence_id="e1",
            subject_id="c1",
            claim="workflow claim",
            source_url="https://example.com",
            source_type="web",
            snippet="snippet",
            captured_at="2026-04-02",
            freshness_score=0.5,
            confidence=0.9,
        )
    )
    state.findings.append(
        Finding(
            finding_id="f1",
            subject_id="c1",
            dimension="workflow",
            summary="Workflow summary.",
            evidence_ids=["e1"],
            confidence=0.8,
        )
    )

    decision = CoverageJudge(required_dimensions=["workflow", "pricing"]).run(state)

    assert decision.judge_type == "coverage"
    assert decision.target_scope == "confirmed_candidates"
    assert decision.verdict == ReviewVerdict.FAIL
    assert any("pricing" in item for item in decision.required_actions)


def test_challenger_warns_when_why_candidate_mentions_platform_and_shape_is_stable():
    from jingyantai.runtime.judges import Challenger

    state = RunState(
        run_id="run-1",
        target="Claude Code",
        current_phase=Phase.CHALLENGE,
        budget=_minimal_budget(),
        round_index=1,
    )
    state.candidates.append(
        Candidate(
            candidate_id="c1",
            name="Platform-ish",
            canonical_url="https://p.dev",
            status=CandidateStatus.CONFIRMED,
            relevance_score=0.9,
            why_candidate="AI platform that also offers a terminal agent",
        )
    )

    decision = Challenger().run(state)

    assert isinstance(decision, ReviewDecision)
    assert decision.judge_type == "challenger"
    assert decision.target_scope == "candidate_fit"
    assert decision.verdict == ReviewVerdict.WARN


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
            Candidate(
                candidate_id="c3",
                name="Second",
                canonical_url="https://second.dev",
                status=CandidateStatus.PRIORITIZED,
                relevance_score=0.8,
                why_candidate="second",
            ),
        ]
    )
    state.open_questions.append(
        OpenQuestion(
            question="What is the pricing model?",
            target_subject="c2",
            priority=GapPriority.HIGH,
            owner_role="analyst",
            created_by="coverage_judge",
        )
    )

    snapshot = ContextCompactor().compact(state)

    assert "Claude Code" in snapshot
    assert "converge" in snapshot.lower()
    assert "Top" in snapshot
    assert "Second" in snapshot
    assert "What is the pricing model?" in snapshot
