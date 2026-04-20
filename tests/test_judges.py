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
    UncertaintyItem,
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
    from jingyantai.runtime.policies import StopBar

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

    state.evidence.append(
        Evidence(
            evidence_id="e1",
            subject_id="c1",
            claim="Workflow claim for Competitor One",
            source_url="https://example.com/c1",
            source_type="web",
            snippet="snippet",
            captured_at="2026-04-02",
            freshness_score=0.5,
            confidence=0.9,
            supports_or_conflicts="supports",
        )
    )

    decision = StopJudge(required_dimensions=["workflow", "pricing"], stop_bar=StopBar(min_confirmed_candidates=1)).run(
        state
    )

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


def test_stop_judge_continues_with_hard_gate_reason_and_no_gap_tickets_when_hard_gate_fails():
    from jingyantai.runtime.judges import StopJudge
    from jingyantai.runtime.policies import StopBar

    state = RunState(
        run_id="run-1",
        target="Claude Code",
        current_phase=Phase.DECIDE,
        budget=_minimal_budget(),
    )
    state.candidates.append(
        Candidate(
            candidate_id="a",
            name="Aider",
            canonical_url="https://aider.chat",
            status=CandidateStatus.CONFIRMED,
            relevance_score=0.9,
            why_candidate="terminal coding agent",
        )
    )

    stop = StopJudge(["positioning"], stop_bar=StopBar.default())
    decision = stop.run(state)

    assert decision.verdict == StopVerdict.CONTINUE
    assert "hard gate" in decision.reasons[0].lower()
    assert decision.gap_tickets == []


def test_stop_judge_hard_gate_runs_before_required_dimensions_empty_early_return():
    from jingyantai.runtime.judges import StopJudge

    state = RunState(
        run_id="run-1",
        target="Claude Code",
        current_phase=Phase.DECIDE,
        budget=_minimal_budget(),
    )
    state.candidates.append(
        Candidate(
            candidate_id="a",
            name="Aider",
            canonical_url="https://aider.chat",
            status=CandidateStatus.CONFIRMED,
            relevance_score=0.9,
            why_candidate="terminal coding agent",
        )
    )

    decision = StopJudge(required_dimensions=[]).run(state)

    assert decision.verdict == StopVerdict.CONTINUE
    assert "hard gate" in decision.reasons[0].lower()
    assert decision.gap_tickets == []


def test_stop_bar_rejects_min_confirmed_candidates_zero():
    from pydantic import ValidationError

    from jingyantai.runtime.policies import StopBar

    try:
        StopBar(min_confirmed_candidates=0)
        assert False, "Expected ValidationError for min_confirmed_candidates=0"
    except ValidationError:
        pass


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


def test_evidence_judge_is_not_pass_on_stale_evidence():
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
            freshness_score=0.05,
            confidence=0.9,
            supports_or_conflicts="supports",
        )
    )

    decision = EvidenceJudge().run(state)

    assert decision.judge_type == "evidence"
    assert decision.verdict != ReviewVerdict.PASS


def test_evidence_judge_uses_quality_rubric_thresholds():
    from jingyantai.runtime.judges import EvidenceJudge
    from jingyantai.runtime.policies import QualityRubric

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
            freshness_score=0.75,
            confidence=0.75,
            supports_or_conflicts="supports",
        )
    )

    rubric = QualityRubric(
        evidence_freshness_threshold=0.7,
        evidence_confidence_threshold=0.8,
    )
    decision = EvidenceJudge(rubric=rubric).run(state)

    assert decision.judge_type == "evidence"
    assert decision.verdict == ReviewVerdict.FAIL
    assert "low-confidence evidence" in decision.reasons[0]


def test_evidence_judge_is_not_pass_on_conflict_evidence():
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
            claim="Conflicts with a key claim",
            source_url="https://example.com",
            source_type="web",
            snippet="snippet",
            captured_at="2026-04-02",
            freshness_score=0.9,
            confidence=0.9,
            supports_or_conflicts="conflicts",
        )
    )

    decision = EvidenceJudge().run(state)

    assert decision.judge_type == "evidence"
    assert decision.verdict != ReviewVerdict.PASS


def test_stop_judge_continues_with_hard_gate_reason_when_confirmed_below_threshold():
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
    assert "hard gate" in decision.reasons[0].lower()
    assert decision.gap_tickets == []


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


def test_coverage_judge_uses_quality_rubric_required_dimensions_by_default():
    from jingyantai.runtime.judges import CoverageJudge
    from jingyantai.runtime.policies import QualityRubric

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
            freshness_score=0.9,
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

    decision = CoverageJudge(
        rubric=QualityRubric(required_dimensions=["workflow", "pricing"])
    ).run(state)

    assert decision.verdict == ReviewVerdict.FAIL
    assert any(item == "Competitor One: pricing" for item in decision.required_actions)


def test_coverage_and_stop_judges_do_not_count_other_candidate_evidence_as_coverage():
    from jingyantai.runtime.judges import CoverageJudge, StopJudge

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
                candidate_id="a",
                name="Alpha",
                canonical_url="https://a.dev",
                status=CandidateStatus.CONFIRMED,
                relevance_score=0.9,
                why_candidate="direct",
            ),
            Candidate(
                candidate_id="b",
                name="Beta",
                canonical_url="https://b.dev",
                status=CandidateStatus.CONFIRMED,
                relevance_score=0.8,
                why_candidate="direct",
            ),
            Candidate(
                candidate_id="c",
                name="Gamma",
                canonical_url="https://c.dev",
                status=CandidateStatus.CONFIRMED,
                relevance_score=0.7,
                why_candidate="direct",
            ),
        ]
    )
    state.evidence.extend(
        [
            Evidence(
                evidence_id="e-b",
                subject_id="b",
                claim="workflow claim for Beta",
                source_url="https://example.com/b",
                source_type="web",
                snippet="snippet",
                captured_at="2026-04-02",
                freshness_score=0.5,
                confidence=0.9,
            ),
            Evidence(
                evidence_id="e-c",
                subject_id="c",
                claim="workflow claim for Gamma",
                source_url="https://example.com/c",
                source_type="web",
                snippet="snippet",
                captured_at="2026-04-02",
                freshness_score=0.5,
                confidence=0.9,
            ),
        ]
    )
    state.findings.extend(
        [
            # BUG case: Alpha "workflow" finding references Beta's evidence id.
            Finding(
                finding_id="f-a",
                subject_id="a",
                dimension="workflow",
                summary="Workflow summary for Alpha.",
                evidence_ids=["e-b"],
                confidence=0.8,
            ),
            Finding(
                finding_id="f-b",
                subject_id="b",
                dimension="workflow",
                summary="Workflow summary for Beta.",
                evidence_ids=["e-b"],
                confidence=0.8,
            ),
            Finding(
                finding_id="f-c",
                subject_id="c",
                dimension="workflow",
                summary="Workflow summary for Gamma.",
                evidence_ids=["e-c"],
                confidence=0.8,
            ),
        ]
    )

    coverage = CoverageJudge(required_dimensions=["workflow"]).run(state)
    assert coverage.verdict == ReviewVerdict.FAIL
    assert any(item == "Alpha: workflow" for item in coverage.required_actions)

    stop = StopJudge(required_dimensions=["workflow"]).run(state)
    assert stop.verdict == StopVerdict.CONTINUE
    assert any(
        ticket.gap_type == "coverage"
        and ticket.target_scope == "Alpha"
        and ticket.blocking_reason == "Missing dimensions: workflow"
        for ticket in stop.gap_tickets
    )


def test_conflict_evidence_does_not_count_as_coverage_for_coverage_and_stop_judges():
    from jingyantai.runtime.judges import CoverageJudge, StopJudge

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
                candidate_id="a",
                name="Alpha",
                canonical_url="https://a.dev",
                status=CandidateStatus.CONFIRMED,
                relevance_score=0.9,
                why_candidate="direct",
            ),
            Candidate(
                candidate_id="b",
                name="Beta",
                canonical_url="https://b.dev",
                status=CandidateStatus.CONFIRMED,
                relevance_score=0.8,
                why_candidate="direct",
            ),
            Candidate(
                candidate_id="c",
                name="Gamma",
                canonical_url="https://c.dev",
                status=CandidateStatus.CONFIRMED,
                relevance_score=0.7,
                why_candidate="direct",
            ),
        ]
    )
    state.evidence.extend(
        [
            Evidence(
                evidence_id="e-a",
                subject_id="a",
                claim="Workflow claim for Alpha (conflict)",
                source_url="https://example.com/a",
                source_type="web",
                snippet="snippet",
                captured_at="2026-04-02",
                freshness_score=0.9,
                confidence=0.9,
                supports_or_conflicts="conflicts",
            ),
            Evidence(
                evidence_id="e-b",
                subject_id="b",
                claim="Workflow claim for Beta",
                source_url="https://example.com/b",
                source_type="web",
                snippet="snippet",
                captured_at="2026-04-02",
                freshness_score=0.9,
                confidence=0.9,
                supports_or_conflicts="supports",
            ),
            Evidence(
                evidence_id="e-c",
                subject_id="c",
                claim="Workflow claim for Gamma",
                source_url="https://example.com/c",
                source_type="web",
                snippet="snippet",
                captured_at="2026-04-02",
                freshness_score=0.9,
                confidence=0.9,
                supports_or_conflicts="supports",
            ),
        ]
    )
    state.findings.extend(
        [
            Finding(
                finding_id="f-a",
                subject_id="a",
                dimension="workflow",
                summary="Workflow summary for Alpha.",
                evidence_ids=["e-a"],
                confidence=0.8,
            ),
            Finding(
                finding_id="f-b",
                subject_id="b",
                dimension="workflow",
                summary="Workflow summary for Beta.",
                evidence_ids=["e-b"],
                confidence=0.8,
            ),
            Finding(
                finding_id="f-c",
                subject_id="c",
                dimension="workflow",
                summary="Workflow summary for Gamma.",
                evidence_ids=["e-c"],
                confidence=0.8,
            ),
        ]
    )

    coverage = CoverageJudge(required_dimensions=["workflow"]).run(state)
    assert coverage.verdict == ReviewVerdict.FAIL
    assert any(item == "Alpha: workflow" for item in coverage.required_actions)

    stop = StopJudge(required_dimensions=["workflow"]).run(state)
    assert stop.verdict == StopVerdict.CONTINUE
    assert any(ticket.gap_type == "coverage" and ticket.target_scope == "Alpha" for ticket in stop.gap_tickets)


def test_stop_judge_continues_when_review_signals_or_open_questions_or_uncertainties_exist():
    from jingyantai.runtime.judges import StopJudge

    state = RunState(
        run_id="run-1",
        target="Claude Code",
        current_phase=Phase.STOP,
        budget=_minimal_budget(),
        round_index=2,
    )
    state.candidates.extend(
        [
            Candidate(
                candidate_id="a",
                name="Alpha",
                canonical_url="https://a.dev",
                status=CandidateStatus.CONFIRMED,
                relevance_score=0.9,
                why_candidate="direct",
            ),
            Candidate(
                candidate_id="b",
                name="Beta",
                canonical_url="https://b.dev",
                status=CandidateStatus.CONFIRMED,
                relevance_score=0.8,
                why_candidate="direct",
            ),
            Candidate(
                candidate_id="c",
                name="Gamma",
                canonical_url="https://c.dev",
                status=CandidateStatus.CONFIRMED,
                relevance_score=0.7,
                why_candidate="direct",
            ),
        ]
    )
    state.evidence.extend(
        [
            Evidence(
                evidence_id="e-a",
                subject_id="a",
                claim="workflow claim a",
                source_url="https://example.com/a",
                source_type="web",
                snippet="snippet",
                captured_at="2026-04-02",
                freshness_score=0.9,
                confidence=0.9,
                supports_or_conflicts="supports",
            ),
            Evidence(
                evidence_id="e-b",
                subject_id="b",
                claim="workflow claim b",
                source_url="https://example.com/b",
                source_type="web",
                snippet="snippet",
                captured_at="2026-04-02",
                freshness_score=0.9,
                confidence=0.9,
                supports_or_conflicts="supports",
            ),
            Evidence(
                evidence_id="e-c",
                subject_id="c",
                claim="workflow claim c",
                source_url="https://example.com/c",
                source_type="web",
                snippet="snippet",
                captured_at="2026-04-02",
                freshness_score=0.9,
                confidence=0.9,
                supports_or_conflicts="supports",
            ),
        ]
    )
    state.findings.extend(
        [
            Finding(
                finding_id="f-a",
                subject_id="a",
                dimension="workflow",
                summary="Workflow a",
                evidence_ids=["e-a"],
                confidence=0.8,
            ),
            Finding(
                finding_id="f-b",
                subject_id="b",
                dimension="workflow",
                summary="Workflow b",
                evidence_ids=["e-b"],
                confidence=0.8,
            ),
            Finding(
                finding_id="f-c",
                subject_id="c",
                dimension="workflow",
                summary="Workflow c",
                evidence_ids=["e-c"],
                confidence=0.8,
            ),
        ]
    )
    state.review_decisions.append(
        ReviewDecision(
            judge_type="evidence",
            target_scope="run",
            verdict=ReviewVerdict.WARN,
            reasons=["needs more corroboration"],
            required_actions=["add independent sources"],
        )
    )
    state.open_questions.append(
        OpenQuestion(
            question="Open question still unresolved",
            target_subject="a",
            priority=GapPriority.MEDIUM,
            owner_role="analyst",
            created_by="coverage",
        )
    )
    state.uncertainties.append(
        UncertaintyItem(
            statement="Uncertain pricing model",
            impact="could change competitor ranking",
            resolvability="medium",
            required_evidence="pricing page snapshot",
            owner_role="analyst",
        )
    )

    decision = StopJudge(required_dimensions=["workflow"]).run(state)

    assert decision.verdict == StopVerdict.CONTINUE
    assert "Quality bar not met" in decision.reasons
    assert decision.gap_tickets
    assert any(ticket.gap_type == "review_decisions" for ticket in decision.gap_tickets)
    assert any(ticket.gap_type == "open_questions" for ticket in decision.gap_tickets)
    assert any(ticket.gap_type == "uncertainties" for ticket in decision.gap_tickets)


def test_stop_judge_uses_quality_rubric_required_dimensions_by_default():
    from jingyantai.runtime.judges import StopJudge
    from jingyantai.runtime.policies import QualityRubric, StopBar

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
                candidate_id="a",
                name="Alpha",
                canonical_url="https://a.dev",
                status=CandidateStatus.CONFIRMED,
                relevance_score=0.9,
                why_candidate="direct",
            ),
            Candidate(
                candidate_id="b",
                name="Beta",
                canonical_url="https://b.dev",
                status=CandidateStatus.CONFIRMED,
                relevance_score=0.8,
                why_candidate="direct",
            ),
            Candidate(
                candidate_id="c",
                name="Gamma",
                canonical_url="https://c.dev",
                status=CandidateStatus.CONFIRMED,
                relevance_score=0.7,
                why_candidate="direct",
            ),
        ]
    )
    state.evidence.extend(
        [
            Evidence(
                evidence_id="e-a",
                subject_id="a",
                claim="workflow claim a",
                source_url="https://example.com/a",
                source_type="web",
                snippet="snippet",
                captured_at="2026-04-02",
                freshness_score=0.9,
                confidence=0.9,
                supports_or_conflicts="supports",
            ),
            Evidence(
                evidence_id="e-b",
                subject_id="b",
                claim="workflow claim b",
                source_url="https://example.com/b",
                source_type="web",
                snippet="snippet",
                captured_at="2026-04-02",
                freshness_score=0.9,
                confidence=0.9,
                supports_or_conflicts="supports",
            ),
            Evidence(
                evidence_id="e-c",
                subject_id="c",
                claim="workflow claim c",
                source_url="https://example.com/c",
                source_type="web",
                snippet="snippet",
                captured_at="2026-04-02",
                freshness_score=0.9,
                confidence=0.9,
                supports_or_conflicts="supports",
            ),
        ]
    )
    state.findings.extend(
        [
            Finding(
                finding_id="f-a",
                subject_id="a",
                dimension="workflow",
                summary="Workflow a",
                evidence_ids=["e-a"],
                confidence=0.8,
            ),
            Finding(
                finding_id="f-b",
                subject_id="b",
                dimension="workflow",
                summary="Workflow b",
                evidence_ids=["e-b"],
                confidence=0.8,
            ),
            Finding(
                finding_id="f-c",
                subject_id="c",
                dimension="workflow",
                summary="Workflow c",
                evidence_ids=["e-c"],
                confidence=0.8,
            ),
        ]
    )

    decision = StopJudge(
        stop_bar=StopBar(min_confirmed_candidates=3),
        rubric=QualityRubric(required_dimensions=["workflow"]),
    ).run(state)

    assert decision.verdict == StopVerdict.STOP


def test_stop_judge_blocks_stop_when_high_impact_uncertainties_exceed_stop_bar():
    from jingyantai.runtime.judges import StopJudge
    from jingyantai.runtime.policies import StopBar

    state = RunState(
        run_id="run-1",
        target="Claude Code",
        current_phase=Phase.STOP,
        budget=_minimal_budget(),
        round_index=1,
    )
    for candidate_id, name in [("a", "Alpha"), ("b", "Beta"), ("c", "Gamma")]:
        state.candidates.append(
            Candidate(
                candidate_id=candidate_id,
                name=name,
                canonical_url=f"https://{name.lower()}.dev",
                status=CandidateStatus.CONFIRMED,
                relevance_score=0.9,
                why_candidate="direct",
            )
        )
        state.evidence.append(
            Evidence(
                evidence_id=f"e-{candidate_id}",
                subject_id=candidate_id,
                claim=f"workflow claim {name}",
                source_url=f"https://example.com/{candidate_id}",
                source_type="web",
                snippet="snippet",
                captured_at="2026-04-02",
                freshness_score=0.9,
                confidence=0.9,
                supports_or_conflicts="supports",
            )
        )
        state.findings.append(
            Finding(
                finding_id=f"f-{candidate_id}",
                subject_id=candidate_id,
                dimension="workflow",
                summary=f"Workflow {name}",
                evidence_ids=[f"e-{candidate_id}"],
                confidence=0.8,
            )
        )
    state.uncertainties.append(
        UncertaintyItem(
            statement="Alpha pricing could change competitor ranking",
            impact="could change competitor ranking",
            resolvability="medium",
            required_evidence="official pricing page",
            owner_role="analyst",
        )
    )

    decision = StopJudge(
        required_dimensions=["workflow"],
        stop_bar=StopBar(min_confirmed_candidates=3, max_high_impact_uncertainties=0),
    ).run(state)

    assert decision.verdict == StopVerdict.CONTINUE
    assert any("high-impact" in reason.lower() for reason in decision.reasons)
    assert any(ticket.gap_type == "uncertainties" for ticket in decision.gap_tickets)


def test_stop_judge_emits_more_specific_gap_ticket_scope_for_open_questions_and_uncertainties():
    from jingyantai.runtime.judges import StopJudge

    state = RunState(
        run_id="run-1",
        target="Claude Code",
        current_phase=Phase.STOP,
        budget=_minimal_budget(),
        round_index=2,
    )
    for candidate_id, name in [("a", "Alpha"), ("b", "Beta"), ("c", "Gamma")]:
        state.candidates.append(
            Candidate(
                candidate_id=candidate_id,
                name=name,
                canonical_url=f"https://{name.lower()}.dev",
                status=CandidateStatus.CONFIRMED,
                relevance_score=0.9,
                why_candidate="direct",
            )
        )
        state.evidence.append(
            Evidence(
                evidence_id=f"e-{candidate_id}",
                subject_id=candidate_id,
                claim=f"workflow claim {name}",
                source_url=f"https://example.com/{candidate_id}",
                source_type="web",
                snippet="snippet",
                captured_at="2026-04-02",
                freshness_score=0.9,
                confidence=0.9,
                supports_or_conflicts="supports",
            )
        )
        state.findings.append(
            Finding(
                finding_id=f"f-{candidate_id}",
                subject_id=candidate_id,
                dimension="workflow",
                summary=f"Workflow {name}",
                evidence_ids=[f"e-{candidate_id}"],
                confidence=0.8,
            )
        )

    state.open_questions.append(
        OpenQuestion(
            question="Pricing page still unclear",
            target_subject="Alpha",
            priority=GapPriority.MEDIUM,
            owner_role="analyst",
            created_by="coverage",
        )
    )
    state.uncertainties.append(
        UncertaintyItem(
            statement="Alpha pricing tiers remain unclear",
            impact="high",
            resolvability="medium",
            required_evidence="pricing page",
            owner_role="analyst",
        )
    )

    decision = StopJudge(required_dimensions=["workflow"]).run(state)

    assert any(ticket.gap_type == "open_questions" and ticket.target_scope == "Alpha" for ticket in decision.gap_tickets)
    assert any(ticket.gap_type == "uncertainties" and ticket.target_scope == "Alpha" for ticket in decision.gap_tickets)


def test_stop_judge_reports_coverage_ratio_when_threshold_is_not_met():
    from jingyantai.runtime.judges import StopJudge
    from jingyantai.runtime.policies import StopBar

    state = RunState(
        run_id="run-1",
        target="Claude Code",
        current_phase=Phase.STOP,
        budget=_minimal_budget(),
        round_index=1,
    )
    for candidate_id, name in [("a", "Alpha"), ("b", "Beta"), ("c", "Gamma")]:
        state.candidates.append(
            Candidate(
                candidate_id=candidate_id,
                name=name,
                canonical_url=f"https://{name.lower()}.dev",
                status=CandidateStatus.CONFIRMED,
                relevance_score=0.9,
                why_candidate="direct",
            )
        )
    for candidate_id in ["a", "b"]:
        state.evidence.append(
            Evidence(
                evidence_id=f"e-{candidate_id}",
                subject_id=candidate_id,
                claim=f"workflow claim {candidate_id}",
                source_url=f"https://example.com/{candidate_id}",
                source_type="web",
                snippet="snippet",
                captured_at="2026-04-02",
                freshness_score=0.9,
                confidence=0.9,
                supports_or_conflicts="supports",
            )
        )
        state.findings.append(
            Finding(
                finding_id=f"f-{candidate_id}",
                subject_id=candidate_id,
                dimension="workflow",
                summary=f"Workflow {candidate_id}",
                evidence_ids=[f"e-{candidate_id}"],
                confidence=0.8,
            )
        )

    decision = StopJudge(
        required_dimensions=["workflow"],
        stop_bar=StopBar(min_confirmed_candidates=3, min_coverage_ratio=1.0),
    ).run(state)

    assert decision.verdict == StopVerdict.CONTINUE
    assert any("coverage ratio" in reason.lower() for reason in decision.reasons)
    assert any(ticket.gap_type == "coverage" for ticket in decision.gap_tickets)


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
