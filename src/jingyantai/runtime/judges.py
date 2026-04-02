from __future__ import annotations

from jingyantai.domain.models import GapTicket, ReviewDecision, RunState, StopDecision
from jingyantai.domain.phases import CandidateStatus, GapPriority, ReviewVerdict, StopVerdict


MIN_EVIDENCE_CONFIDENCE = 0.6
MIN_EVIDENCE_FRESHNESS = 0.2


def _is_acceptable_support_evidence(*, candidate_id: str, evidence: object) -> bool:
    # Keep this tiny and explicit; tests lock the semantics.
    if getattr(evidence, "subject_id", None) != candidate_id:
        return False
    if getattr(evidence, "supports_or_conflicts", "supports") != "supports":
        return False
    if getattr(evidence, "confidence", 0.0) < MIN_EVIDENCE_CONFIDENCE:
        return False
    if getattr(evidence, "freshness_score", 0.0) < MIN_EVIDENCE_FRESHNESS:
        return False
    return True


def _covered_dimensions_for_candidate(
    state: RunState, *, candidate_id: str, required_dimensions: list[str]
) -> set[str]:
    evidence_by_id = {evidence.evidence_id: evidence for evidence in state.evidence}

    covered: set[str] = set()
    for finding in state.findings:
        if finding.subject_id != candidate_id:
            continue
        if finding.dimension not in required_dimensions:
            continue
        if not finding.evidence_ids:
            continue
        if all(
            evidence_id in evidence_by_id
            and _is_acceptable_support_evidence(candidate_id=candidate_id, evidence=evidence_by_id[evidence_id])
            for evidence_id in finding.evidence_ids
        ):
            covered.add(finding.dimension)
    return covered


class EvidenceJudge:
    def run(self, state: RunState) -> ReviewDecision:
        conflicts = [evidence for evidence in state.evidence if evidence.supports_or_conflicts != "supports"]
        stale = [evidence for evidence in state.evidence if evidence.freshness_score < MIN_EVIDENCE_FRESHNESS]
        weak = [evidence for evidence in state.evidence if evidence.confidence < MIN_EVIDENCE_CONFIDENCE]

        if conflicts or stale or weak:
            pieces: list[str] = []
            if conflicts:
                pieces.append(
                    "conflict evidence: " + ", ".join(evidence.evidence_id for evidence in conflicts)
                )
            if stale:
                pieces.append(
                    "stale evidence: " + ", ".join(evidence.evidence_id for evidence in stale)
                )
            if weak:
                weak_labels = [f"{evidence.evidence_id}({evidence.confidence:.2f})" for evidence in weak]
                pieces.append("low-confidence evidence: " + ", ".join(weak_labels))
            return ReviewDecision(
                judge_type="evidence",
                target_scope="run",
                verdict=ReviewVerdict.FAIL,
                reasons=["Evidence quality gate failed: " + "; ".join(pieces) + "."],
                required_actions=[
                    "Replace, corroborate, or remove non-supporting / stale / low-confidence evidence IDs: "
                    + ", ".join({evidence.evidence_id for evidence in conflicts + stale + weak})
                    + "."
                ],
            )

        return ReviewDecision(
            judge_type="evidence",
            target_scope="run",
            verdict=ReviewVerdict.PASS,
            reasons=["Evidence quality gate passed."],
            required_actions=[],
        )


class CoverageJudge:
    def __init__(self, required_dimensions: list[str]) -> None:
        self.required_dimensions = list(required_dimensions)

    def run(self, state: RunState) -> ReviewDecision:
        if not self.required_dimensions:
            return ReviewDecision(
                judge_type="coverage",
                target_scope="confirmed_candidates",
                verdict=ReviewVerdict.WARN,
                reasons=["No required_dimensions configured for CoverageJudge."],
            )

        confirmed = [candidate for candidate in state.candidates if candidate.status == CandidateStatus.CONFIRMED]
        if not confirmed:
            return ReviewDecision(
                judge_type="coverage",
                target_scope="confirmed_candidates",
                verdict=ReviewVerdict.WARN,
                reasons=["No confirmed candidates to evaluate coverage for."],
            )

        missing_by_candidate: dict[str, list[str]] = {}
        for candidate in confirmed:
            covered = _covered_dimensions_for_candidate(
                state, candidate_id=candidate.candidate_id, required_dimensions=self.required_dimensions
            )
            missing = [dimension for dimension in self.required_dimensions if dimension not in covered]
            if missing:
                missing_by_candidate[candidate.candidate_id] = missing

        if missing_by_candidate:
            reasons: list[str] = []
            required_actions: list[str] = []
            for candidate in confirmed:
                missing = missing_by_candidate.get(candidate.candidate_id)
                if not missing:
                    continue
                reasons.append(f"{candidate.name} missing: {', '.join(missing)}")
                required_actions.extend([f"{candidate.name}: {dimension}" for dimension in missing])
            return ReviewDecision(
                judge_type="coverage",
                target_scope="confirmed_candidates",
                verdict=ReviewVerdict.FAIL,
                reasons=reasons,
                required_actions=required_actions,
            )

        return ReviewDecision(
            judge_type="coverage",
            target_scope="confirmed_candidates",
            verdict=ReviewVerdict.PASS,
            reasons=["All required dimensions covered for confirmed candidates."],
            required_actions=[],
        )


class Challenger:
    def run(self, state: RunState) -> ReviewDecision:
        scoped = [
            candidate
            for candidate in state.candidates
            if candidate.status in {CandidateStatus.PRIORITIZED, CandidateStatus.CONFIRMED}
        ]
        if not scoped:
            return ReviewDecision(
                judge_type="challenger",
                target_scope="candidate_fit",
                verdict=ReviewVerdict.WARN,
                reasons=[
                    "No prioritized/confirmed candidates to challenge yet.",
                    "Consider alternative discovery angles.",
                ],
                required_actions=["Expand candidate discovery and validate direct-competitor fit."],
            )

        platform_named = [c for c in scoped if "platform" in c.why_candidate.lower()]
        if platform_named:
            return ReviewDecision(
                judge_type="challenger",
                target_scope="candidate_fit",
                verdict=ReviewVerdict.WARN,
                reasons=[
                    "Some candidates are described as a platform; confirm they are direct competitors.",
                    "Platform-language can indicate a broader product scope than a terminal-native coding agent.",
                ],
                required_actions=[f"Verify direct competitor fit for: {', '.join(c.name for c in platform_named)}."],
            )

        return ReviewDecision(
            judge_type="challenger",
            target_scope="candidate_fit",
            verdict=ReviewVerdict.PASS,
            reasons=["No platform-language found in why_candidate for prioritized/confirmed candidates."],
            required_actions=[],
        )


class StopJudge:
    def __init__(self, required_dimensions: list[str]) -> None:
        self.required_dimensions = list(required_dimensions)

    def run(self, state: RunState) -> StopDecision:
        confirmed = [candidate for candidate in state.candidates if candidate.status == CandidateStatus.CONFIRMED]
        if not self.required_dimensions:
            return StopDecision(
                verdict=StopVerdict.CONTINUE,
                reasons=["Quality bar not met"],
                gap_tickets=[],
            )

        gap_tickets: list[GapTicket] = []

        unresolved_review = [
            decision
            for decision in state.review_decisions
            if decision.verdict in {ReviewVerdict.FAIL, ReviewVerdict.WARN}
        ]
        if unresolved_review:
            gap_tickets.append(
                GapTicket(
                    gap_type="review_decisions",
                    target_scope="run",
                    blocking_reason="Unresolved review decisions exist.",
                    owner_role="lead_researcher",
                    acceptance_rule="Resolve all FAIL/WARN review decisions.",
                    deadline_round=state.round_index + 1,
                    priority=GapPriority.HIGH,
                    retry_count=0,
                )
            )

        if state.open_questions:
            gap_tickets.append(
                GapTicket(
                    gap_type="open_questions",
                    target_scope="run",
                    blocking_reason="Open questions remain.",
                    owner_role="analyst",
                    acceptance_rule="Answer all open questions with direct evidence.",
                    deadline_round=state.round_index + 1,
                    priority=GapPriority.MEDIUM,
                    retry_count=0,
                )
            )

        if state.uncertainties:
            gap_tickets.append(
                GapTicket(
                    gap_type="uncertainties",
                    target_scope="run",
                    blocking_reason="Uncertainties remain.",
                    owner_role="analyst",
                    acceptance_rule="Resolve or explicitly bound key uncertainties with direct evidence.",
                    deadline_round=state.round_index + 1,
                    priority=GapPriority.MEDIUM,
                    retry_count=0,
                )
            )

        if len(confirmed) < 3:
            gap_tickets.append(
                GapTicket(
                    gap_type="candidate_count",
                    target_scope="run",
                    blocking_reason="Need at least 3 confirmed competitors.",
                    owner_role="scout",
                    acceptance_rule="Confirm at least 3 direct competitors.",
                    deadline_round=state.round_index + 1,
                    priority=GapPriority.HIGH,
                    retry_count=0,
                )
            )

        for candidate in confirmed:
            covered = _covered_dimensions_for_candidate(
                state, candidate_id=candidate.candidate_id, required_dimensions=self.required_dimensions
            )
            missing = [dimension for dimension in self.required_dimensions if dimension not in covered]
            if not missing:
                continue
            gap_tickets.append(
                GapTicket(
                    gap_type="coverage",
                    target_scope=candidate.name,
                    blocking_reason=(
                        "Missing dimensions: "
                        f"{', '.join(missing)}"
                    ),
                    owner_role="analyst",
                    acceptance_rule="Cover all required dimensions with direct evidence.",
                    deadline_round=state.round_index + 1,
                    priority=GapPriority.HIGH,
                    retry_count=0,
                )
            )

        if gap_tickets:
            return StopDecision(
                verdict=StopVerdict.CONTINUE,
                reasons=["Quality bar not met"],
                gap_tickets=gap_tickets,
            )

        if not confirmed:
            return StopDecision(
                verdict=StopVerdict.CONTINUE,
                reasons=["Quality bar not met"],
                gap_tickets=[],
            )

        if self.required_dimensions:
            return StopDecision(
                verdict=StopVerdict.STOP,
                reasons=["Quality bar met"],
                gap_tickets=[],
            )

        return StopDecision(
            verdict=StopVerdict.CONTINUE,
            reasons=["Missing required dimensions definition; continue."],
            gap_tickets=[],
        )
